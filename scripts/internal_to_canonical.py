#!/usr/bin/env python3
"""
Convert the legacy internal event log (events/events.sample.jsonl — dotted
``visit.*`` envelopes) into a canonical PDF-schema seed
(events/canonical.seed.jsonl), tagged as Store 1 = ``STORE_BLR_002``.

This gives the canonical store REAL data on a fresh clone, so the acceptance
gate's ``GET /stores/STORE_BLR_002/metrics`` answers with genuine numbers
without re-running detection. Pure stdlib (no pydantic/cv2) so it runs anywhere.

Mapping
-------
  visit.entered        -> ENTRY                 (+group_id/group_size metadata)
  (no visit.entered)   -> NO ENTRY              (floor/billing track = engagement,
                                                 not a door entry — footfall stays a
                                                 true door count, no per-camera recount)
  visit.entered_zone   -> ZONE_ENTER
  visit.exited_zone    -> ZONE_EXIT (+ZONE_DWELL every 30s, synthesized)
  visit.approached_cash-> BILLING_QUEUE_JOIN    (+queue_depth = concurrency proxy)
  visit.ended          -> EXIT
  track.staff_classified marks the visitor is_staff on every emitted event

Timestamps are IST in the source (+05:30) and emitted as ISO-8601 UTC (Z).
Demographics are NOT synthesized here (the legacy data has none) — the live
worker populates gender_pred/age_pred; the seed simply omits them honestly.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

STORE_ID = "STORE_BLR_002"
CONFIDENCE = 0.9                       # seed lacks per-detection conf; documented
CASH_ZONE = "cash_counter"
DWELL_STEP_MS = 30_000                 # ZONE_DWELL cadence (PDF: every 30s)
MAX_DWELL_EVENTS = 8
QUEUE_CONC_MS = 30_000                 # window for the queue-depth concurrency proxy
_NS = uuid.UUID("6f1a7b3e-0c2d-4e5f-8a9b-1c2d3e4f5a6b")


def to_utc_z(ts: str) -> str:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def ms(ts: str) -> int:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def eid(*parts) -> str:
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


def _iso(ms_val: int) -> str:
    return datetime.fromtimestamp(ms_val / 1000, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _ev(event_type, vid, cam, ts, is_staff, *, zone, dwell_ms, metadata=None):
    return {
        "event_id": eid(STORE_ID, vid, event_type, ts, zone),
        "store_id": STORE_ID,
        "camera_id": cam,
        "visitor_id": vid,
        "event_type": event_type,
        "timestamp": to_utc_z(ts) if "T" in str(ts) else ts,
        "zone_id": zone,
        "dwell_ms": int(dwell_ms),
        "is_staff": bool(is_staff),
        "confidence": CONFIDENCE,
        "metadata": dict(metadata or {}),
    }


def convert(src: str, dst: str, store_id: str | None = None) -> int:
    global STORE_ID
    if store_id:
        STORE_ID = store_id
    rows = [json.loads(l) for l in open(src) if l.strip()]

    # staff visitors + per-visitor event lists + global cash timeline
    staff: set = set()
    by_visit: dict = defaultdict(list)
    cash_ts: list = []
    for e in rows:
        p = e.get("payload", {})
        vid = p.get("visit_id")
        if e["type"] == "track.staff_classified" and vid:
            staff.add(vid)
        if vid:
            by_visit[vid].append(e)
        if e["type"] == "visit.approached_cash":
            cash_ts.append(ms(e["ts"]))
    cash_ts.sort()

    def queue_depth(t_ms: int) -> int:
        lo = t_ms - QUEUE_CONC_MS
        return sum(1 for c in cash_ts if lo <= c <= t_ms)

    out: list = []
    for vid, evs in by_visit.items():
        evs.sort(key=lambda e: ms(e["ts"]))
        is_staff = vid in staff
        cam0 = evs[0].get("camera") or "cam3"
        first_ts = evs[0]["ts"]
        entered = next((e for e in evs if e["type"] == "visit.entered"), None)
        ended = next((e for e in evs if e["type"] == "visit.ended"), None)

        emitted: list = []  # (sort_ts_ms, tiebreak, canonical_dict)

        # ENTRY — ONLY for a real entry-line crossing (visit.entered, emitted by
        # door cameras). Floor / billing tracks never cross the doorway, so they
        # must NOT manufacture an entry; they contribute zone / billing
        # engagement only. This is what makes footfall a true *door count*
        # instead of recounting the same shopper once per camera they appear on.
        if entered is not None:
            ep = entered["payload"]
            ent_ts = entered["ts"]
            ent_cam = entered.get("camera") or cam0
            ent_meta = {}
            if ep.get("group_id"):
                ent_meta["group_id"] = ep["group_id"]
            if ep.get("group_size"):
                ent_meta["group_size"] = ep["group_size"]
            emitted.append((ms(ent_ts), 0, _ev("ENTRY", vid, ent_cam, ent_ts, is_staff,
                                               zone=None, dwell_ms=0, metadata=ent_meta)))

        for e in evs:
            t = e["ts"]
            cam = e.get("camera") or cam0
            p = e["payload"]
            typ = e["type"]
            if typ == "visit.entered_zone":
                emitted.append((ms(t), 1, _ev("ZONE_ENTER", vid, cam, t, is_staff,
                                              zone=p.get("zone"), dwell_ms=0)))
            elif typ == "visit.exited_zone":
                zone = p.get("zone")
                dwell = int(p.get("dwell_ms") or 0)
                exit_ms = ms(t)
                enter_ms = exit_ms - dwell
                k = 1
                while k * DWELL_STEP_MS <= dwell and k <= MAX_DWELL_EVENTS:
                    d_ms = enter_ms + k * DWELL_STEP_MS
                    emitted.append((d_ms, 1, _ev("ZONE_DWELL", vid, cam,
                                                 _iso(d_ms), is_staff, zone=zone,
                                                 dwell_ms=k * DWELL_STEP_MS)))
                    k += 1
                emitted.append((exit_ms, 2, _ev("ZONE_EXIT", vid, cam, t, is_staff,
                                                zone=zone, dwell_ms=dwell)))
            elif typ == "visit.approached_cash":
                emitted.append((ms(t), 1, _ev("BILLING_QUEUE_JOIN", vid, cam, t,
                                              is_staff, zone=CASH_ZONE, dwell_ms=0,
                                              metadata={"queue_depth": queue_depth(ms(t))})))

        # EXIT (from visit.ended, last)
        if ended is not None:
            ep = ended["payload"]
            emitted.append((ms(ended["ts"]) + 1, 9, _ev("EXIT", vid,
                            ended.get("camera") or cam0, ended["ts"], is_staff,
                            zone=None, dwell_ms=0,
                            metadata={"reason": ep.get("reason")})))

        emitted.sort(key=lambda x: (x[0], x[1]))
        for seq, (_ts, _tb, ev) in enumerate(emitted, 1):
            ev["metadata"]["session_seq"] = seq
            out.append(ev)

    out.sort(key=lambda ev: ev["timestamp"])
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w") as f:
        for ev in out:
            f.write(json.dumps(ev) + "\n")
    return len(out)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="legacy visit.* JSONL -> canonical seed")
    ap.add_argument("src", nargs="?", default="events/events.sample.jsonl")
    ap.add_argument("dst", nargs="?", default="events/canonical.seed.jsonl")
    ap.add_argument("--store-id", default="STORE_BLR_002",
                    help="canonical store_id to tag (Store 1=STORE_BLR_002, Store 2=STORE_BLR_009)")
    a = ap.parse_args()
    n = convert(a.src, a.dst, a.store_id)
    print(f"wrote {n} canonical events -> {a.dst} (store {a.store_id})")
