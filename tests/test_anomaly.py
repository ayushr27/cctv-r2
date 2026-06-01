"""
Unit tests for the three anomaly detectors.

Each detector gets a synthetic event stream that SHOULD fire and one that
should NOT, asserting the boundary behavior directly. Detectors read through a
real in-memory EventStore (built by writing synthetic events to a temp JSONL
and calling store.load) and a lightweight fake POS object.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services.anomaly_detect import (  # noqa: E402
    ConversionDropDetector,
    FootfallDropDetector,
    Window,
    ZoneStarvationDetector,
    run_detectors,
)
from services.event_store import EventStore  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def ts(hh, mm=0, ss=0):
    return datetime(2026, 4, 10, hh, mm, ss, tzinfo=IST).isoformat()


def _event(etype, when, *, visit_id="v", zone=None, extra=None):
    from ulid import ULID

    payload = {"visit_id": visit_id, "track_id": 1}
    if etype == "visit.entered":
        payload.update({"entry_line": "entry_line", "group_id": None, "group_size": 1})
    if etype == "visit.entered_zone":
        payload["zone"] = zone or "z"
    if etype == "visit.exited_zone":
        payload.update({"zone": zone or "z", "dwell_ms": 1000})
    if etype == "visit.ended":
        payload.update({"total_dwell_ms": 1000, "zones_visited": [], "reason": "track_lost"})
    if extra:
        payload.update(extra)
    return {"event_id": str(ULID()), "ts": when, "type": etype, "camera": "cam1", "payload": payload}


def build_store(events, tmp_path) -> EventStore:
    p = tmp_path / "ev.jsonl"
    with open(p, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    s = EventStore()
    s.load(str(p))
    return s


class FakeBill:
    def __init__(self, when):
        self.ts_ms = int(datetime.fromisoformat(when).timestamp() * 1000)


class FakePos:
    def __init__(self, bill_times):
        self._bills = [FakeBill(t) for t in bill_times]

    def get_bills(self, from_=None, to_=None):
        return list(self._bills)


# ---------------------------------------------------------------------------
# 1) FootfallDrop
# ---------------------------------------------------------------------------


def test_footfall_drop_fires(tmp_path):
    # 60 min baseline with natural variance (4-7 per bucket), then an EMPTY
    # bucket. A varied baseline gives stdev>0 so the z-score is meaningful.
    counts = [5, 6, 4, 7, 5, 6, 4, 5, 7, 5, 6, 4]  # 12 buckets, mean ~5.3
    events = []
    for b, n in enumerate(counts):
        base = 13 * 60 + b * 5
        for k in range(n):
            events.append(_event("visit.entered", ts(base // 60, base % 60), visit_id=f"v{b}_{k}"))
    # current bucket: empty (observed 0). To exist as a bucket boundary at all
    # we anchor the window end via one entry two buckets later, leaving the
    # 13th bucket at zero between baseline and that anchor.
    far = 13 * 60 + 13 * 5  # one entry 5 min after the empty bucket
    events.append(_event("visit.entered", ts(far // 60, far % 60), visit_id="anchor"))

    store = build_store(events, tmp_path)
    out = FootfallDropDetector().run(store, FakePos([]), Window(None, None))
    assert out, "expected a footfall_drop anomaly"
    a = [x for x in out if x["observed"] == 0.0][0]
    assert a["kind"] == "footfall_drop"
    assert a["observed"] < a["expected_p50"]
    assert a["z_score"] < -2
    assert a["severity"] in ("warning", "critical")


def test_footfall_drop_silent_when_steady(tmp_path):
    events = []
    for b in range(14):
        base = 13 * 60 + b * 5
        for k in range(5):
            events.append(_event("visit.entered", ts(base // 60, base % 60), visit_id=f"v{b}_{k}"))
    store = build_store(events, tmp_path)
    out = FootfallDropDetector().run(store, FakePos([]), Window(None, None))
    assert out == [], f"expected no anomalies, got {out}"


# ---------------------------------------------------------------------------
# 2) ConversionDrop
# ---------------------------------------------------------------------------


def test_conversion_drop_fires(tmp_path):
    # Hour A (15:00): 20 footfall, 10 bills -> conv 0.50
    # Hour B (16:00): 20 footfall, 1 bill  -> conv 0.05  (< 0.5*median, footfall>10)
    events = []
    for i in range(20):
        events.append(_event("visit.entered", ts(15, i % 59), visit_id=f"a{i}"))
    for i in range(20):
        events.append(_event("visit.entered", ts(16, i % 59), visit_id=f"b{i}"))
    store = build_store(events, tmp_path)
    bills = [ts(15, m) for m in range(10)] + [ts(16, 1)]
    out = ConversionDropDetector().run(store, FakePos(bills), Window(None, None))
    assert out, "expected a conversion_drop anomaly"
    assert out[0]["kind"] == "conversion_drop"
    assert out[0]["observed"] < out[0]["expected_p50"]


def test_conversion_drop_silent_when_low_footfall(tmp_path):
    # Same conversion gap but footfall <= 10 -> must NOT fire.
    events = []
    for i in range(5):
        events.append(_event("visit.entered", ts(15, i), visit_id=f"a{i}"))
    for i in range(5):
        events.append(_event("visit.entered", ts(16, i), visit_id=f"b{i}"))
    store = build_store(events, tmp_path)
    bills = [ts(15, 0), ts(15, 1), ts(15, 2)]
    out = ConversionDropDetector().run(store, FakePos(bills), Window(None, None))
    assert out == [], f"expected no anomalies (footfall too low), got {out}"


# ---------------------------------------------------------------------------
# 3) ZoneStarvation
# ---------------------------------------------------------------------------


def test_zone_starvation_fires(tmp_path):
    # Zone 'derm' seen once at 10:05, then nothing until close -> big gap.
    events = [_event("visit.entered_zone", ts(10, 5), zone="derm", visit_id="z1")]
    store = build_store(events, tmp_path)
    out = ZoneStarvationDetector().run(store, FakePos([]), Window(None, None))
    assert out, "expected a zone_starvation anomaly"
    assert {a["kind"] for a in out} == {"zone_starvation"}
    assert any(a["severity"] == "warning" for a in out)  # 10:05 -> 22:00 tail


def test_zone_starvation_silent_when_busy(tmp_path):
    # An entry every 30 min from 10:00 to 22:00 -> no >=45 min gap.
    events = []
    t = datetime(2026, 4, 10, 10, 0, tzinfo=IST)
    end = datetime(2026, 4, 10, 22, 0, tzinfo=IST)
    i = 0
    while t <= end:
        events.append(_event("visit.entered_zone", t.isoformat(), zone="derm", visit_id=f"z{i}"))
        t += timedelta(minutes=30)
        i += 1
    store = build_store(events, tmp_path)
    out = ZoneStarvationDetector().run(store, FakePos([]), Window(None, None))
    assert out == [], f"expected no starvation, got {len(out)} anomalies"


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_kind_filter(tmp_path):
    events = [_event("visit.entered_zone", ts(10, 5), zone="derm", visit_id="z1")]
    store = build_store(events, tmp_path)
    only = run_detectors(store, FakePos([]), None, None, kinds=["zone_starvation"])
    assert only and all(a["kind"] == "zone_starvation" for a in only)
    none = run_detectors(store, FakePos([]), None, None, kinds=["footfall_drop"])
    assert none == []


def test_results_sorted_by_severity(tmp_path):
    events = [_event("visit.entered_zone", ts(10, 30), zone="derm", visit_id="z1")]
    store = build_store(events, tmp_path)
    out = run_detectors(store, FakePos([]), None, None)
    rank = {"critical": 0, "warning": 1, "info": 2}
    ranks = [rank[a["severity"]] for a in out]
    assert ranks == sorted(ranks), "anomalies must be severity-sorted"
