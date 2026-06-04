# PROMPT: "Test re-entry gating (time + distance) so a person who steps out and returns keeps one visit_id."
# CHANGES MADE: Added just-outside-the-gate (new visit) and tie-break-by-distance cases.

"""
Tests for temporal+spatial re-entry gating in worker.events.EventDeriver.

A track that ends and a NEW track that reappears soon after, near the last
position, should be treated as the same visit (visit_id reused). Outside the
time gate (8s) or the distance gate (100px), it's a new visit.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from events import EventDeriver  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 4, 10, 20, 0, 0, tzinfo=IST)

# Interior-style camera: no entry_line, so tracks auto-activate and get a
# visit_id on first detection (footfall is owned by the door camera).
ZONES = {"_meta": {}}


def bbox_at(fx, fy, w=40, h=120):
    """Build a bbox whose feet point (bottom-center) is (fx, fy)."""
    return [fx - w / 2, fy - h, fx + w / 2, fy]


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def visit_id_of(deriver, track_id):
    return deriver.tracks[track_id].visit_id


def _deriver():
    # generous end timeout so the "still-open" track isn't swept before the gate
    return EventDeriver(ZONES, end_timeout_s=30.0, reentry_s=8.0, reentry_px=100.0)


def test_reentry_reuses_visit_id_within_gates():
    d = _deriver()
    # track 1 seen at t=0 and t=5s at ~(100,100)
    d.process_detection(0, at(0), 1, bbox_at(100, 100))
    d.process_detection(50, at(5), 1, bbox_at(100, 100))
    v1 = visit_id_of(d, 1)
    # track 2 appears at t=6s near (110,105): within 8s and within 100px -> REUSE
    d.process_detection(60, at(6), 2, bbox_at(110, 105))
    assert visit_id_of(d, 2) == v1


def test_new_visit_when_outside_time_gate():
    d = _deriver()
    d.process_detection(0, at(0), 1, bbox_at(100, 100))
    d.process_detection(50, at(5), 1, bbox_at(100, 100))
    v1 = visit_id_of(d, 1)
    # track 2 at t=15s: gap 10s > 8s gate -> NEW visit
    d.process_detection(150, at(15), 2, bbox_at(110, 105))
    assert visit_id_of(d, 2) != v1


def test_new_visit_when_outside_distance_gate():
    d = _deriver()
    d.process_detection(0, at(0), 1, bbox_at(100, 100))
    d.process_detection(50, at(5), 1, bbox_at(100, 100))
    v1 = visit_id_of(d, 1)
    # track 2 at t=6s but at (500,500): ~566px > 100px gate -> NEW visit
    d.process_detection(60, at(6), 2, bbox_at(500, 500))
    assert visit_id_of(d, 2) != v1


def test_reentry_picks_nearest_open_track():
    d = _deriver()
    d.process_detection(0, at(0), 1, bbox_at(100, 100))
    d.process_detection(0, at(0), 2, bbox_at(160, 100))  # 60px from track 1
    # new track 3 at (150,100): nearer track 2 (10px) than track 1 (50px)
    d.process_detection(50, at(5), 3, bbox_at(150, 100))
    assert visit_id_of(d, 3) == visit_id_of(d, 2)


# A camera WITH zones + entry_line, to exercise the full event-emission path
# (visit.entered, entered_zone/exited_zone with dwell, approached_cash, ended).
ZONES_FULL = {
    "_meta": {},
    "entry_line": {"type": "line", "points": [[0, 100], [200, 100]],
                   "direction": "in_when_y_decreases"},
    "shelf": {"type": "polygon", "points": [[0, 0], [80, 0], [80, 80], [0, 80]]},
    "cash_counter": {"type": "polygon", "points": [[120, 0], [200, 0], [200, 80], [120, 80]]},
}


def _types(events):
    return [e.type for e in events]


def test_full_flow_emits_all_event_types():
    d = EventDeriver(ZONES_FULL, end_timeout_s=30.0)
    # below line -> above line at (40,*) => crosses entry (y decreases) => entered
    d.process_detection(0, at(0), 1, bbox_at(40, 130))
    d.process_detection(10, at(1), 1, bbox_at(40, 60))   # crossed + inside shelf
    d.process_detection(20, at(3), 1, bbox_at(40, 60))   # dwell in shelf
    d.process_detection(30, at(5), 1, bbox_at(160, 60))  # left shelf -> cash zone
    d.process_detection(40, at(6), 1, bbox_at(160, 60))
    events = d.finalize()
    types = set(_types(events))
    assert "visit.entered" in types
    assert "visit.entered_zone" in types
    assert "visit.exited_zone" in types
    assert "visit.approached_cash" in types
    assert "visit.ended" in types
    # the ended event carries cumulative dwell + zones visited
    ended = [e for e in events if e.type == "visit.ended"][0]
    assert ended.payload.total_dwell_ms > 0
    assert "shelf" in ended.payload.zones_visited


def test_exited_zone_has_positive_dwell():
    d = EventDeriver(ZONES_FULL, end_timeout_s=30.0)
    d.process_detection(0, at(0), 1, bbox_at(40, 130))
    d.process_detection(10, at(1), 1, bbox_at(40, 60))   # enter shelf
    d.process_detection(20, at(4), 1, bbox_at(160, 60))  # leave shelf after ~3s
    events = d.finalize()
    exited = [e for e in events if e.type == "visit.exited_zone" and e.payload.zone == "shelf"]
    assert exited and exited[0].payload.dwell_ms >= 2000
