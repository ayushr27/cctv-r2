#!/usr/bin/env python3
"""
Interactive zone annotator — turns the provisional worker/zones.json into
real coordinates calibrated against an actual camera frame.

Usage:
  # grab a frame from a video and annotate it
  python scripts/annotate_zones.py --video "CCTV Footage/CAM 1.mp4" --seconds 300

  # or annotate an existing image
  python scripts/annotate_zones.py --image data/layout/frame.jpg

Workflow:
  1. A frame is shown.
  2. For each zone you're prompted for, left-click the polygon vertices
     (2 points for the entry line, 3+ for polygons), then press ENTER.
  3. Press ENTER with no clicks to skip a zone.
  4. The result is written to worker/zones.json.

Requires (dev only): opencv-python, matplotlib.
  pip install opencv-python matplotlib
"""

import argparse
import json
from pathlib import Path

ZONE_PROMPTS = [
    ("entry_line", "line", "Entry line: click 2 points across the doorway"),
    ("cash_counter", "polygon", "Cash counter: click the polygon corners"),
    ("dermdoc", "polygon", "DermDoc zone"),
    ("makeup_unit", "polygon", "Makeup Unit zone"),
    ("skincare", "polygon", "Skincare zone"),
    ("fragrance", "polygon", "Fragrance zone"),
    ("haircare", "polygon", "Haircare zone"),
]


def grab_frame(video: str, seconds: float):
    import cv2

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(seconds * fps))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"could not read frame at {seconds}s")
    return frame[:, :, ::-1]  # BGR -> RGB for matplotlib


def load_image(path: str):
    import cv2

    img = cv2.imread(path)
    if img is None:
        raise SystemExit(f"cannot read image: {path}")
    return img[:, :, ::-1]


def annotate(frame) -> dict:
    import matplotlib.pyplot as plt

    h, w = frame.shape[:2]
    zones = {
        "_meta": {
            "frame_size": [int(w), int(h)],
            "coordinate_system": "pixels, origin top-left, +x right, +y down",
        }
    }
    for name, ztype, prompt in ZONE_PROMPTS:
        n = 2 if ztype == "line" else -1  # -1 == until ENTER
        fig, ax = plt.subplots(figsize=(14, 8))
        ax.imshow(frame)
        ax.set_title(f"{prompt}  —  click, then press ENTER ( ENTER alone = skip )")
        pts = plt.ginput(n=n, timeout=0)
        plt.close(fig)
        if not pts:
            print(f"  skipped {name}")
            continue
        points = [[round(x, 1), round(y, 1)] for x, y in pts]
        entry = {"type": ztype, "points": points}
        if name == "entry_line":
            entry["direction"] = "in_when_y_decreases"
        zones[name] = entry
        print(f"  {name}: {len(points)} points")
    return zones


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="path to a video file")
    src.add_argument("--image", help="path to an image file")
    ap.add_argument("--seconds", type=float, default=300.0,
                    help="timestamp to grab from --video (default 300)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent /
                                         "worker" / "zones.json"))
    args = ap.parse_args()

    frame = grab_frame(args.video, args.seconds) if args.video else load_image(args.image)
    zones = annotate(frame)

    out = Path(args.out)
    out.write_text(json.dumps(zones, indent=2) + "\n")
    print(f"wrote {len(zones) - 1} zones to {out}")


if __name__ == "__main__":
    main()
