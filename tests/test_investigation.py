"""
Tests for the privacy-preserving investigation detectors
(services/investigation.py): unbilled cash approach + long unattended dwell.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services.event_store import EventStore  # noqa: E402
from services.investigation import (  # noqa: E402
    LongDwellDetector,
    UnbilledCashApproachDetector,
    Window,
    find_incidents,
)

IST = timezone(timedelta(hours=5, minutes=30))


def ts(hh, mm=0, ss=0):
    return datetime(2026, 4, 10, hh, mm, ss, tzinfo=IST).isoformat()


def _event(etype, when, *, visit_id="v", camera="cam5", dwell_ms=1000, zones=None):
    from ulid import ULID

    payload = {"visit_id": visit_id, "track_id": 1}
    if etype == "visit.ended":
        payload.update({"total_dwell_ms": dwell_ms, "zones_visited": zones or [],
                        "reason": "track_lost"})
    if etype == "track.staff_classified":
        payload["evidence"] = {"total_dwell_ms": dwell_ms, "zones_count": 0, "cash_passes": 0}
    return {"event_id": str(ULID()), "ts": when, "type": etype, "camera": camera, "payload": payload}


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


WIN = Window(None, None)


# ---- unbilled cash approach ----

def test_unbilled_cash_fires_and_is_critical(tmp_path):
    # 3 approaches in the 20:10 bucket, 0 bills -> 3 unmatched -> critical
    events = [
        _event("visit.approached_cash", ts(20, 10, 1), visit_id="a"),
        _event("visit.approached_cash", ts(20, 10, 20), visit_id="b"),
        _event("visit.approached_cash", ts(20, 11, 0), visit_id="c"),
    ]
    store = build_store(events, tmp_path)
    out = UnbilledCashApproachDetector().run(store, FakePos([]), WIN)
    assert len(out) == 1
    inc = out[0]
    assert inc["kind"] == "unbilled_cash_approach"
    assert inc["severity"] == "critical"      # 3 unmatched
    assert inc["camera"] == "cam5"
    assert inc["clip_ref"]["camera"] == "cam5" and inc["clip_ref"]["review"]


def test_unbilled_cash_silent_when_bills_match(tmp_path):
    # 2 approaches, 2 bills in the same 5-min bucket -> nothing unmatched
    events = [
        _event("visit.approached_cash", ts(20, 10, 1), visit_id="a"),
        _event("visit.approached_cash", ts(20, 10, 30), visit_id="b"),
    ]
    store = build_store(events, tmp_path)
    out = UnbilledCashApproachDetector().run(store, FakePos([ts(20, 10, 5), ts(20, 10, 40)]), WIN)
    assert out == []


# ---- long unattended dwell ----

def test_long_dwell_fires_for_customer(tmp_path):
    events = [_event("visit.ended", ts(20, 11, 0), visit_id="c1",
                     camera="cam1", dwell_ms=120_000, zones=["faces_canada"])]
    store = build_store(events, tmp_path)
    out = LongDwellDetector().run(store, FakePos([]), WIN)
    assert len(out) == 1
    assert out[0]["kind"] == "long_unattended_dwell"
    assert out[0]["camera"] == "cam1"
    assert "120s" in out[0]["evidence"]


def test_long_dwell_excludes_staff(tmp_path):
    # same long dwell, but the visit is tagged staff -> not an incident
    events = [
        _event("visit.ended", ts(20, 11, 0), visit_id="s1", camera="cam1", dwell_ms=120_000),
        _event("track.staff_classified", ts(20, 11, 0), visit_id="s1", camera="cam1"),
    ]
    store = build_store(events, tmp_path)
    assert "s1" in store.staff_visit_ids
    out = LongDwellDetector().run(store, FakePos([]), WIN)
    assert out == []


def test_long_dwell_silent_when_short(tmp_path):
    events = [_event("visit.ended", ts(20, 11, 0), visit_id="c1", dwell_ms=10_000)]
    store = build_store(events, tmp_path)
    assert LongDwellDetector().run(store, FakePos([]), WIN) == []


# ---- registry ----

def test_find_incidents_sorted_and_filtered(tmp_path):
    events = [
        _event("visit.approached_cash", ts(20, 10, 1), visit_id="a"),
        _event("visit.approached_cash", ts(20, 10, 9), visit_id="b"),
        _event("visit.ended", ts(20, 11, 0), visit_id="c1", camera="cam1", dwell_ms=120_000),
    ]
    store = build_store(events, tmp_path)
    pos = FakePos([])
    allinc = find_incidents(store, pos, None, None)
    # critical/warning (cash) sorts before info (dwell)
    assert allinc[0]["severity"] in ("critical", "warning")
    assert allinc[-1]["kind"] == "long_unattended_dwell"
    # kind filter
    only = find_incidents(store, pos, None, None, kinds=["long_unattended_dwell"])
    assert only and all(i["kind"] == "long_unattended_dwell" for i in only)
