"""
YOLOv8n + BoT-SORT detection CLI.

Reads a video file, runs person detection at a target FPS, applies BoT-SORT
tracking, and writes one JSONL line per detection to the output file.

Output schema per line:
  {"frame": int, "ts": str (ISO8601+05:30), "track_id": int,
   "bbox": [x1,y1,x2,y2], "confidence": float, "video_ts_ms": int}
"""

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import cv2
import structlog

from config import DEFAULT_FPS, PERSON_CLASS, YOLO_MODEL, get_start_datetime
from store_config import uniform_spec
from uniform import uniform_fraction

logger = structlog.get_logger()

# Staff-uniform colour matching lives in uniform.py (per-store: black for
# Store 1, pink for Store 2). detect.py resolves the store's spec once and
# measures the per-detection uniform fraction; the field names top_dark/bot_dark
# are kept for downstream compatibility — they now mean "uniform-match fraction".


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YOLOv8n + BoT-SORT detection writer")
    parser.add_argument("--video", required=True, help="Path to input video file")
    parser.add_argument(
        "--out",
        default="events/raw_detections.jsonl",
        help="Output JSONL path (default: events/raw_detections.jsonl)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=DEFAULT_FPS,
        help=f"Target ingestion frame rate (default: {DEFAULT_FPS})",
    )
    parser.add_argument(
        "--sample-seconds",
        type=int,
        default=None,
        help="Only process first N seconds of video",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Inference device: cpu or cuda (default: cpu)",
    )
    parser.add_argument(
        "--start-time",
        default="10:00:00",
        help="Store opening time HH:MM:SS IST to anchor timestamps (default: 10:00:00)",
    )
    parser.add_argument(
        "--camera",
        default=None,
        help="Camera label written into every detection record (e.g. cam3)",
    )
    parser.add_argument(
        "--store",
        default="STORE_BLR_002",
        help="Store id selecting the staff-uniform colour (default: STORE_BLR_002)",
    )
    return parser.parse_args()


def run_detection(args: argparse.Namespace) -> None:
    from ultralytics import YOLO  # deferred so `python config.py` stays fast

    configure_logging()
    log = logger.bind(video=args.video, out=args.out, fps=args.fps)

    # Per-store staff-uniform colour (black for Store 1, pink for Store 2).
    try:
        spec = uniform_spec(args.store)
    except KeyError:
        spec = {"mode": "black"}
        log.warning("unknown_store_uniform_default_black", store=args.store)

    video_path = Path(args.video)
    if not video_path.exists():
        log.error("video_not_found")
        sys.exit(1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".jsonl.tmp")

    # Probe native fps + total frames without keeping the capture open
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.error("cannot_open_video")
        sys.exit(1)
    native_fps: float = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    # Frame stride so effective FPS ≈ args.fps
    stride = max(1, round(native_fps / args.fps))

    # Hard limit when --sample-seconds is given
    max_frame: int | None = None
    if args.sample_seconds is not None:
        max_frame = int(args.sample_seconds * native_fps)

    start_dt = get_start_datetime(args.start_time)

    log.info(
        "detection_starting",
        native_fps=round(native_fps, 2),
        total_frames=total_frames,
        stride=stride,
        max_frame=max_frame,
        device=args.device,
    )

    model = YOLO(YOLO_MODEL)

    # Tuned BoT-SORT (larger track_buffer etc.) to de-fragment tracks; falls back
    # to the packaged default if the file was stripped from the image.
    tuned = Path(__file__).with_name("botsort_tuned.yaml")
    tracker_cfg = str(tuned) if tuned.exists() else "botsort.yaml"
    log.info("tracker_config", tracker=tracker_cfg)

    wall_start = time.monotonic()
    frames_processed = 0
    total_detections = 0
    track_ids_seen: set[int] = set()

    with open(tmp_path, "w") as fout:
        for result in model.track(
            source=str(video_path),
            classes=[PERSON_CLASS],
            persist=True,
            tracker=tracker_cfg,
            device=args.device,
            stream=True,
            verbose=False,
            vid_stride=stride,
        ):
            # result.path holds the source; the frame index is tracked via frames_processed
            orig_frame: int = frames_processed * stride

            if max_frame is not None and orig_frame > max_frame:
                break

            video_ts_ms = int((orig_frame / native_fps) * 1000)
            ts_str = (start_dt + timedelta(milliseconds=video_ts_ms)).isoformat()

            if result.boxes is not None and result.boxes.id is not None:
                boxes = result.boxes
                frame_img = result.orig_img  # BGR ndarray for clothing-darkness
                for i in range(len(boxes)):
                    track_id = int(boxes.id[i].item())
                    conf = float(boxes.conf[i].item())
                    xyxy = boxes.xyxy[i].tolist()
                    bbox = [round(v, 1) for v in xyxy]

                    top_dark, bot_dark = (0.0, 0.0)
                    if frame_img is not None:
                        top_dark, bot_dark = uniform_fraction(frame_img, xyxy, spec)

                    record = {
                        "frame": orig_frame,
                        "ts": ts_str,
                        "track_id": track_id,
                        "bbox": bbox,
                        "confidence": round(conf, 4),
                        "video_ts_ms": video_ts_ms,
                        "top_dark": top_dark,
                        "bot_dark": bot_dark,
                    }
                    if args.camera:
                        record["camera"] = args.camera
                    fout.write(json.dumps(record) + "\n")
                    total_detections += 1
                    track_ids_seen.add(track_id)

            frames_processed += 1

            if frames_processed % 1000 == 0:
                elapsed = time.monotonic() - wall_start
                log.info(
                    "progress",
                    frames_processed=frames_processed,
                    total_detections=total_detections,
                    unique_tracks=len(track_ids_seen),
                    elapsed_seconds=round(elapsed, 1),
                )

    # Atomic rename so readers never see a partial file
    tmp_path.rename(out_path)

    wall_elapsed = round(time.monotonic() - wall_start, 2)
    log.info(
        "detection_complete",
        total_frames_processed=frames_processed,
        total_detections=total_detections,
        unique_track_ids=len(track_ids_seen),
        wall_clock_seconds=wall_elapsed,
        out=str(out_path),
    )


if __name__ == "__main__":
    run_detection(parse_args())
