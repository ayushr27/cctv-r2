"""
Tests for the behavioral staff classifier (worker/classify.py).

Pure logic, no heavy deps — covers the >=2-of-3-signals rule, the per-camera
median-multiple long-dwell path, the strict full-day thresholds (=> zero staff
on clip-scale data), and the aggregate -> classify -> emit pipeline.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from classify import (  # noqa: E402
    DEFAULT_DWELL_FLOOR_S,
    DEFAULT_DWELL_MEDIAN_MULT,
    DEFAULT_MIN_SIGNALS,
    DEFAULT_ZONES_MIN,
    VisitAgg,
    aggregate_visits,
    build_staff_events,
    classify,
    per_camera_median_dwell,
)
from schemas import (  # noqa: E402
    VisitApproachedCash,
    VisitApproachedCashPayload,
    VisitEnded,
    VisitEndedPayload,
)

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 4, 10, 20, 0, 0, tzinfo=IST)

DEFAULTS = dict(
    dwell_floor_s=DEFAULT_DWELL_FLOOR_S,
    dwell_median_mult=DEFAULT_DWELL_MEDIAN_MULT,
    zones_min=DEFAULT_ZONES_MIN,
    min_signals=DEFAULT_MIN_SIGNALS,
)


def agg(vid, *, camera="cam1", dwell_ms=0, zones=0, cash=0, ended=True, track_id=1):
    v = VisitAgg(vid)
    v.camera = camera
    v.track_id = track_id
    v.total_dwell_ms = dwell_ms
    v.zones_count = zones
    v.cash_passes = cash
    v.ts = T0 if ended else None
    return v


def test_staff_long_dwell_plus_multi_zone():
    # 139s dwell (> 40s floor) + 2 zones => long_dwell + multi_zone = 2 signals
    visits = {"s1": agg("s1", dwell_ms=139_000, zones=2)}
    assert classify(visits, **DEFAULTS) == ["s1"]


def test_staff_long_dwell_plus_cash_anchor():
    # 50s dwell (> floor) + 1 cash pass => long_dwell + cash_anchor = 2 signals
    visits = {"s1": agg("s1", dwell_ms=50_000, zones=0, cash=1)}
    assert classify(visits, **DEFAULTS) == ["s1"]


def test_customer_not_staff():
    # short dwell, single zone, no cash => 0 signals
    visits = {"c1": agg("c1", dwell_ms=3_000, zones=1, cash=0)}
    assert classify(visits, **DEFAULTS) == []


def test_one_signal_is_not_enough():
    # multi_zone alone (3 zones) but brief dwell, no cash => 1 signal => customer
    visits = {"c1": agg("c1", dwell_ms=2_000, zones=3, cash=0)}
    assert classify(visits, **DEFAULTS) == []


def test_median_multiple_path_below_floor():
    # 4 short customers set the cam median ~5s; a 25s visit is BELOW the 40s
    # absolute floor but ABOVE 4x median (20s) -> long_dwell via the median path.
    # Plus a cash pass => long_dwell + cash_anchor = staff.
    visits = {f"c{i}": agg(f"c{i}", camera="cam2", dwell_ms=5_000) for i in range(4)}
    visits["s1"] = agg("s1", camera="cam2", dwell_ms=25_000, cash=1)
    medians = per_camera_median_dwell(visits)
    assert medians["cam2"] == 5_000  # sanity: median established
    staff = classify(visits, **DEFAULTS)
    assert staff == ["s1"]


def test_strict_fullday_thresholds_classify_zero():
    # The plan's literal thresholds can't fire on clip-scale data.
    visits = {
        "a": agg("a", dwell_ms=139_000, zones=2, cash=1),
        "b": agg("b", camera="cam5", dwell_ms=38_000, cash=1),
    }
    staff = classify(
        visits,
        dwell_floor_s=1800,        # 30 min
        dwell_median_mult=999,     # effectively disabled
        zones_min=3,
        min_signals=2,
    )
    assert staff == []


def test_visit_without_end_is_skipped():
    # no visit.ended => ts is None => cannot be scored
    visits = {"x": agg("x", dwell_ms=139_000, zones=3, cash=2, ended=False)}
    assert classify(visits, **DEFAULTS) == []


def test_aggregate_and_emit_pipeline():
    # Build an event stream: one staff-like visit (long dwell + cash) and one
    # brief customer; aggregate -> classify -> emit track.staff_classified.
    events = [
        VisitApproachedCash(
            event_id="e1", ts=T0, camera="cam5",
            payload=VisitApproachedCashPayload(visit_id="s1", track_id=7),
        ),
        VisitEnded(
            event_id="e2", ts=T0 + timedelta(seconds=50), camera="cam5",
            payload=VisitEndedPayload(
                visit_id="s1", track_id=7, total_dwell_ms=50_000,
                zones_visited=["cash_counter"], reason="track_lost",
            ),
        ),
        VisitEnded(
            event_id="e3", ts=T0 + timedelta(seconds=4), camera="cam2",
            payload=VisitEndedPayload(
                visit_id="c1", track_id=8, total_dwell_ms=4_000,
                zones_visited=["makeup_wall"], reason="track_lost",
            ),
        ),
    ]
    visits = aggregate_visits(events)
    assert visits["s1"].cash_passes == 1
    assert visits["s1"].total_dwell_ms == 50_000

    staff_ids = classify(visits, **DEFAULTS)
    assert staff_ids == ["s1"]

    staff_events = build_staff_events(visits, staff_ids)
    assert len(staff_events) == 1
    ev = staff_events[0]
    assert ev.type == "track.staff_classified"
    assert ev.payload.visit_id == "s1"
    assert ev.payload.evidence.total_dwell_ms == 50_000
    assert ev.payload.evidence.cash_passes == 1
