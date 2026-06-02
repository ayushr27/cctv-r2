"""
Tests for footage clip resolution (services/clips.py): in-video offset math,
camera allowlist, and graceful availability when the video file is absent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services import clips  # noqa: E402


def test_offset_from_camera_start():
    # cam5 footage starts 20:09:48; an event at 20:09:58 is +10s in-video.
    c = clips.resolve_clip("cam5", "2026-04-10T20:09:58+05:30", "2026-04-10T20:10:08+05:30")
    assert c is not None
    assert c["camera"] == "cam5"
    assert c["video_url"] == "/clip/cam5"
    assert c["start_s"] == 10.0
    assert c["end_s"] == 20.0


def test_start_clamped_to_zero():
    # window opens before the footage start -> clamp to 0, not negative.
    c = clips.resolve_clip("cam5", "2026-04-10T20:09:40+05:30", "2026-04-10T20:09:58+05:30")
    assert c["start_s"] == 0.0
    assert c["end_s"] == 10.0


def test_unknown_camera_returns_none():
    assert clips.resolve_clip("cam9", "2026-04-10T20:10:00+05:30", "2026-04-10T20:10:10+05:30") is None
    assert clips.resolve_clip(None, "2026-04-10T20:10:00+05:30", None) is None


def test_unavailable_when_outside_footage():
    # 10:00 is hours before the 20:xx clip -> not available even if file exists.
    c = clips.resolve_clip("cam5", "2026-04-10T10:00:00+05:30", "2026-04-10T10:05:00+05:30")
    assert c is not None
    assert c["available"] is False


def test_availability_tracks_file_presence():
    # available is True only if the mp4 is actually on disk for an in-window time.
    c = clips.resolve_clip("cam5", "2026-04-10T20:09:58+05:30", "2026-04-10T20:10:08+05:30")
    expected = clips.video_path("cam5") is not None
    assert c["available"] is expected


def test_video_path_allowlist():
    assert clips.video_path("cam9") is None        # not in CAMERA_START
    assert clips.video_path("../etc/passwd") is None
