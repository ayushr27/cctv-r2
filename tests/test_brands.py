# PROMPT: "Test brand engagement: per-stand dwell joined to POS revenue/units/top-products, with a browsed-but-not-bought signal."
# CHANGES MADE: Added a staff-excluded assertion and a brand-with-no-sales case the first draft skipped.

"""
Tests for brand-stand engagement (services/brands.py): attention (zone dwell,
staff excluded) joined to POS outcome (revenue / units / top products).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services.brands import brand_engagement  # noqa: E402
from services.event_store import EventStore  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def ts(hh, mm=0, ss=0):
    return datetime(2026, 4, 10, hh, mm, ss, tzinfo=IST).isoformat()


def _event(etype, when, *, visit_id="v", zone="faces_canada", dwell_ms=0, camera="cam2"):
    from ulid import ULID

    payload = {"visit_id": visit_id, "track_id": 1}
    if etype == "visit.entered_zone":
        payload["zone"] = zone
    if etype == "visit.exited_zone":
        payload.update({"zone": zone, "dwell_ms": dwell_ms})
    if etype == "track.staff_classified":
        payload["evidence"] = {"total_dwell_ms": dwell_ms, "zones_count": 1, "cash_passes": 0}
    return {"event_id": str(ULID()), "ts": when, "type": etype, "camera": camera, "payload": payload}


def build_store(events, tmp_path) -> EventStore:
    p = tmp_path / "ev.jsonl"
    with open(p, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    s = EventStore()
    s.load(str(p))
    return s


class FakePos:
    def __init__(self, breakdown):
        self._b = breakdown

    def brand_breakdown_in_window(self, from_=None, to=None):
        return self._b


def _stand(stands, name):
    return next(s for s in stands if s["stand"] == name)


def test_engagement_joins_attention_and_sales(tmp_path):
    events = [
        _event("visit.entered_zone", ts(20, 11, 0), visit_id="c1"),
        _event("visit.exited_zone", ts(20, 11, 8), visit_id="c1", dwell_ms=8000),
        _event("visit.entered_zone", ts(20, 11, 5), visit_id="c2"),
        _event("visit.exited_zone", ts(20, 11, 9), visit_id="c2", dwell_ms=4000),
    ]
    store = build_store(events, tmp_path)
    pos = FakePos({"Faces Canada": {"revenue": 15697.0, "units": 33,
                                    "top_products": [("Faces Canada Lipstick", 12)]}})
    stands = brand_engagement(store, pos, None, None)
    fc = _stand(stands, "faces_canada")
    assert fc["visits"] == 2
    assert fc["attention_seconds"] == 12.0          # 8s + 4s
    assert fc["revenue"] == 15697.0                  # joined from its brand
    assert fc["units"] == 33
    assert fc["revenue_per_visit"] == round(15697.0 / 2, 2)
    assert fc["top_products"][0]["product"] == "Faces Canada Lipstick"
    assert fc["signal"] == "converting attention to sales"


def test_staff_excluded_from_attention(tmp_path):
    events = [
        _event("visit.entered_zone", ts(20, 11, 0), visit_id="c1"),
        _event("visit.exited_zone", ts(20, 11, 8), visit_id="c1", dwell_ms=8000),
        # a staff member dwelling at the same stand must NOT count as attention
        _event("visit.entered_zone", ts(20, 11, 0), visit_id="s1"),
        _event("visit.exited_zone", ts(20, 11, 40), visit_id="s1", dwell_ms=40000),
        _event("track.staff_classified", ts(20, 11, 40), visit_id="s1"),
    ]
    store = build_store(events, tmp_path)
    assert "s1" in store.staff_visit_ids
    stands = brand_engagement(store, FakePos({}), None, None)
    fc = _stand(stands, "faces_canada")
    assert fc["visits"] == 1                  # only the customer
    assert fc["attention_seconds"] == 8.0     # staff 40s excluded


def test_browsed_not_bought_signal(tmp_path):
    # lots of attention, zero sales -> merchandising-opportunity signal
    events = [
        _event("visit.entered_zone", ts(20, 11, 0), visit_id="c1"),
        _event("visit.exited_zone", ts(20, 11, 30), visit_id="c1", dwell_ms=30000),
    ]
    store = build_store(events, tmp_path)
    stands = brand_engagement(store, FakePos({}), None, None)
    fc = _stand(stands, "faces_canada")
    assert fc["revenue"] == 0.0
    assert "no sales" in fc["signal"]


def test_ranked_by_attention(tmp_path):
    events = [
        _event("visit.entered_zone", ts(20, 11, 0), visit_id="c1", zone="faces_canada"),
        _event("visit.exited_zone", ts(20, 11, 5), visit_id="c1", zone="faces_canada", dwell_ms=5000),
        _event("visit.entered_zone", ts(20, 11, 0), visit_id="c2", zone="dermdoc", camera="cam1"),
        _event("visit.exited_zone", ts(20, 11, 20), visit_id="c2", zone="dermdoc", camera="cam1", dwell_ms=20000),
    ]
    store = build_store(events, tmp_path)
    stands = brand_engagement(store, FakePos({}), None, None)
    active = [s for s in stands if s["attention_seconds"] > 0]
    assert active[0]["stand"] == "dermdoc"   # 20s ranks above 5s
