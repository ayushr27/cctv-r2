"""
Footage clip resolution — maps an incident/anomaly wall-clock window to an
in-video offset so the dashboard can play the relevant CCTV segment.

Privacy / access note: the /clip endpoint serves RAW footage. That's a
legitimate loss-prevention review action (an authorised operator viewing the
clip for a flagged incident) — but it is also raw video, so in production the
endpoint MUST sit behind authentication. There is no auth in this demo.

The sample clips are short (~2-3 min) and are NOT committed (gitignored). On a
fresh clone without them, resolve_clip returns available=false and the UI falls
back to the text clip reference.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))
FOOTAGE_DATE = "2026-04-10"
MAX_CLIP_S = 600  # generous cap on sample-clip length for availability checks

# Wall-clock time each camera's footage STARTS (read off the on-screen clock at
# ingest). In a real DVR this would come from the recording's metadata. The
# detection pipeline anchors every store's events to FOOTAGE_DATE, so a single
# date works for both stores; only the per-clip start time differs.
CAMERA_START = {
    # Store 1
    "cam1": "20:10:27",
    "cam2": "20:10:02",
    "cam3": "20:10:00",
    "cam5": "20:09:48",
    # Store 2 (mirrors worker/store_config.py so investigation snippets resolve)
    "entry1": "19:39:06",
    "entry2": "19:39:06",
    "zone": "15:27:51",
    "billing": "15:28:00",
}

_VIDEO_DIRS = ["/data/samples", os.path.join(os.path.dirname(__file__), "..", "..", "data", "samples")]


def video_path(camera: str) -> Optional[str]:
    """Resolve the on-disk mp4 for a camera, or None. Allowlist-guarded."""
    if camera not in CAMERA_START:
        return None
    for d in _VIDEO_DIRS:
        p = os.path.join(d, f"{camera}.mp4")
        if os.path.exists(p):
            return p
    return None


def _ms(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return int(dt.timestamp() * 1000)


def _start_ms(camera: str) -> int:
    return int(
        datetime.fromisoformat(f"{FOOTAGE_DATE}T{CAMERA_START[camera]}+05:30").timestamp() * 1000
    )


def resolve_clip(camera: Optional[str], from_: Optional[str], to: Optional[str]) -> Optional[dict]:
    """
    {camera, available, video_url, start_s, end_s} for a wall-clock window, or
    None if no camera. available=false when the window falls outside the footage
    (or the file is absent) — the UI then shows the text reference only.
    """
    if not camera or camera not in CAMERA_START:
        return None
    start_ms = _start_ms(camera)
    f_ms, t_ms = _ms(from_), _ms(to)
    off_from = (f_ms - start_ms) / 1000 if f_ms is not None else 0.0
    off_to = (t_ms - start_ms) / 1000 if t_ms is not None else off_from + 30

    has_file = video_path(camera) is not None
    available = has_file and off_to > 0 and off_from < MAX_CLIP_S

    return {
        "camera": camera,
        "available": available,
        "video_url": f"/clip/{camera}",
        "start_s": round(max(0.0, off_from), 1),
        "end_s": round(max(0.0, off_to), 1),
    }
