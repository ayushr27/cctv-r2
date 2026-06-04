"""
Store intelligence — metrics / funnel / heatmap / anomalies computed live from
the canonical event store (the PDF ``/stores/{id}/*`` contract).

Everything is SESSION-based, not raw-event based: events are grouped per visitor,
re-entries (REENTRY events carrying ``metadata.reentry_of``) collapse back onto
the original visitor so a person who steps out and returns is one unique visitor,
and ``is_staff`` sessions are excluded from every customer metric.

North-Star (PDF §8): conversion = converted visitors / unique visitors, where a
visitor "converted" if they were in the billing zone in the 5-minute window
*before* a POS transaction timestamp.

All functions are zero-traffic safe: an empty store yields zeros + a low
``data_confidence`` flag, never null or an exception.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from services.brands import _ZONE_BRANDS, _signal
from services.canonical_store import canonical_store, is_all_stores
from services.clips import resolve_clip
from services.pos_join import pos
from services.store_map import floor_cameras, pos_store_id

IST = timezone(timedelta(hours=5, minutes=30))

# Conversion: billing-zone presence this long before a POS txn counts (PDF §3.4).
CONVERSION_WINDOW_MS = 5 * 60 * 1000
# Queue spike thresholds on observed queue_depth.
QUEUE_WARN, QUEUE_CRITICAL = 4, 7
# Dead-zone lookback: a known zone with no visits in this trailing window.
DEAD_ZONE_MS = 30 * 60 * 1000
# CONVERSION_DROP baseline — a 7-day average is impossible with one day of data,
# so we compare to a configured expected rate (documented fallback, CHOICES.md).
EXPECTED_CONVERSION = float(os.environ.get("STORE_EXPECTED_CONVERSION", "0.20"))
MIN_VISITORS_FOR_CONV = 5
# Heatmap reliability flag below this many sessions (PDF: <20).
MIN_SESSIONS_CONFIDENT = 20
# Crowding: people on the busiest floor camera at once (peak occupancy).
CROWDING_WARN, CROWDING_CRITICAL = 8, 12
# Billing-queue abandonment share that warrants a flag.
ABANDON_WARN, ABANDON_CRITICAL = 0.4, 0.6
MIN_JOINS_FOR_ABANDON = 3


# ---------------------------------------------------------------------------
# Session construction
# ---------------------------------------------------------------------------


class _Session:
    __slots__ = (
        "visitor_id", "store_id", "is_staff", "first_ms", "last_ms", "entered",
        "zone_dwell", "zones_entered", "billing_ts", "abandoned",
        "gender", "age", "age_bucket", "group", "last_cam",
    )

    def __init__(self, visitor_id: str, store_id: str = "") -> None:
        self.visitor_id = visitor_id
        self.store_id = store_id
        self.is_staff = False
        self.first_ms: Optional[int] = None
        self.last_ms: Optional[int] = None
        self.entered = False
        self.zone_dwell: Dict[str, int] = defaultdict(int)  # zone -> max dwell_ms
        self.zones_entered: set = set()
        self.billing_ts: List[int] = []
        self.abandoned = False
        self.gender: Optional[str] = None
        self.age: Optional[int] = None
        self.age_bucket: Optional[str] = None
        self.group: Optional[int] = None       # ENTRY metadata.group_size
        self.last_cam: Optional[str] = None     # camera of this session's last event


def _resolve_roots(events: List[dict]) -> Dict[str, str]:
    """Map each visitor_id to its root (collapsing REENTRY chains)."""
    parent: Dict[str, str] = {}
    for ev in events:
        if ev["event_type"] == "REENTRY":
            ro = (ev.get("metadata") or {}).get("reentry_of")
            if ro:
                parent[ev["visitor_id"]] = ro

    def root(v: str) -> str:
        seen = set()
        while v in parent and v not in seen:
            seen.add(v)
            v = parent[v]
        return v

    return {v: root(v) for v in {e["visitor_id"] for e in events}}


def build_sessions(
    store_id: str, from_: Optional[str] = None, to_: Optional[str] = None
) -> Tuple[Dict[Tuple[str, str], _Session], List[dict]]:
    events = canonical_store.fetch(store_id, from_, to_)
    roots = _resolve_roots(events)
    # Keyed by (store_id, root visitor) so a cumulative ALL query can never merge
    # two different people who happen to share a track id across stores.
    sessions: Dict[Tuple[str, str], _Session] = {}

    for ev in events:
        r = roots.get(ev["visitor_id"], ev["visitor_id"])
        key = (ev["store_id"], r)
        s = sessions.get(key)
        if s is None:
            s = sessions[key] = _Session(r, ev["store_id"])
        ms = ev["ts_ms"]
        s.first_ms = ms if s.first_ms is None else min(s.first_ms, ms)
        if s.last_ms is None or ms >= s.last_ms:
            s.last_ms = ms
            s.last_cam = ev.get("camera_id")
        if ev["is_staff"]:
            s.is_staff = True
        et = ev["event_type"]
        meta = ev.get("metadata") or {}
        # Demographics can be tagged on ANY of a visitor's events — the enricher
        # tags each visitor's first event, which for a floor-only shopper is a
        # ZONE_* not an ENTRY. Pick up the first non-empty value on any event so
        # the panel describes every in-store visitor, not just door-crossers.
        if meta.get("gender_pred") and s.gender is None:
            s.gender = meta.get("gender_pred")
        if meta.get("age_pred") is not None and s.age is None:
            s.age = meta.get("age_pred")
        if meta.get("age_bucket") and s.age_bucket is None:
            s.age_bucket = meta.get("age_bucket")
        if et in ("ENTRY", "REENTRY"):
            s.entered = True
            if meta.get("group_size") and s.group is None:
                try:
                    s.group = int(meta["group_size"])
                except (TypeError, ValueError):
                    pass
        elif et == "ZONE_ENTER" and ev.get("zone_id"):
            s.zones_entered.add(ev["zone_id"])
        elif et in ("ZONE_EXIT", "ZONE_DWELL") and ev.get("zone_id"):
            z = ev["zone_id"]
            s.zones_entered.add(z)
            s.zone_dwell[z] = max(s.zone_dwell[z], int(ev.get("dwell_ms") or 0))
        elif et == "BILLING_QUEUE_JOIN":
            s.billing_ts.append(ms)
        elif et == "BILLING_QUEUE_ABANDON":
            s.abandoned = True

    return sessions, events


def _customers(sessions: Dict[str, _Session]) -> List[_Session]:
    """Non-staff sessions only — the unit for every customer metric."""
    return [s for s in sessions.values() if not s.is_staff]


def _per_cam_roots(events: List[dict]) -> Tuple[dict, dict]:
    """(customers, staff): store -> camera -> set of distinct ROOT visitor ids."""
    roots = _resolve_roots(events)
    staff_ids = {(e["store_id"], roots.get(e["visitor_id"], e["visitor_id"]))
                 for e in events if e["is_staff"]}
    cust: Dict[str, Dict[Optional[str], set]] = defaultdict(lambda: defaultdict(set))
    stf: Dict[str, Dict[Optional[str], set]] = defaultdict(lambda: defaultdict(set))
    for e in events:
        r = roots.get(e["visitor_id"], e["visitor_id"])
        bucket = stf if (e["store_id"], r) in staff_ids else cust
        bucket[e["store_id"]][e.get("camera_id")].add(r)
    return cust, stf


def _occupancy(store_id: str, events: List[dict]) -> Tuple[int, int, int]:
    """
    (peak_occupancy, total_visitors, staff_count) — summed per store for the ALL
    view (never across stores, since the cameras aren't time-synced and there is
    no cross-camera Re-ID).

      peak_occupancy  most people on the busiest FLOOR camera AT ONCE
                      (occupancy.json ``peak``; fragmentation-proof — a split
                      track only adds an id when the person is NOT in frame).
      total_visitors  busiest floor camera's de-fragmented body count minus the
                      staff seen there (occupancy.json ``visitors`` — distinct
                      after merging split tracks; the honest "how many shopped").
      staff_count     distinct staff on the busiest camera.

    Falls back to the canonical busiest-camera distinct (REENTRY-collapsed) for a
    store that has not been re-detected yet (no occupancy.json) so the endpoint
    never 500s mid-migration.
    """
    occ = canonical_store.occupancy(store_id)
    cust, stf = _per_cam_roots(events)
    stores = set(occ) | {e["store_id"] for e in events}

    peak_t = vis_t = staff_t = 0
    for sid in stores:
        floor = set(floor_cameras(sid))
        staff_n = max((len(v) for v in stf.get(sid, {}).values()), default=0)
        cams = occ.get(sid)
        if cams:
            focc = {c: d for c, d in cams.items() if not floor or c in floor} or cams
            peak = max((int(d.get("peak", 0)) for d in focc.values()), default=0)
            bodies = max((int(d.get("visitors", 0)) for d in focc.values()), default=0)
            visitors = max(bodies - staff_n, 0)
        else:  # no raw occupancy yet → canonical busiest-camera distinct
            cc = cust.get(sid, {})
            fvals = [v for c, v in cc.items() if not floor or c in floor] or list(cc.values())
            visitors = peak = max((len(v) for v in fvals), default=0)
        peak_t += peak
        vis_t += visitors
        staff_t += staff_n
    return peak_t, vis_t, staff_t


def _scale_counts(counts: Dict[str, int], target: int) -> Dict[str, int]:
    """
    Scale a count distribution so the integers sum to ``target`` (footfall),
    preserving proportions via largest-remainder rounding. Keeps panel counts
    (demographics, heatmap) consistent with the de-fragmented footfall headline
    instead of the larger per-camera sample they were tallied from.
    """
    total = sum(counts.values())
    if total <= 0 or target <= 0:
        return {}
    raw = {k: v * target / total for k, v in counts.items()}
    out = {k: int(x) for k, x in raw.items()}
    remainder = target - sum(out.values())
    order = sorted(counts, key=lambda k: raw[k] - out[k], reverse=True)
    for k in order[:max(0, remainder)]:
        out[k] += 1
    return {k: v for k, v in out.items() if v > 0}


def _window(store_id, from_, to_) -> Tuple[Optional[str], Optional[str]]:
    if from_ or to_:
        return from_, to_
    return canonical_store.data_range(store_id)


# ---------------------------------------------------------------------------
# Conversion (North-Star)
# ---------------------------------------------------------------------------


def _billing_offset(pos_id: Optional[str], customers: List["_Session"]) -> int:
    """
    Constant clip-clock skew (ms) to add to CV billing presences so they line up
    with the POS day: the offset that lands the median billing presence on the
    nearest real bill. The cam5 clock is eyeballed off the on-screen clock and can
    sit minutes off; conversion AND the unbilled-cash investigation use the SAME
    correction so they agree (a real sale isn't mislabelled "unbilled").
    """
    txns = pos.transactions(pos_id)
    presences = sorted(bt for s in customers for bt in s.billing_ts)
    if not txns or not presences:
        return 0
    bill_times = [t for t, _ in txns]
    median = presences[len(presences) // 2]
    return min(bill_times, key=lambda t: abs(t - median)) - median


def _conversion(store_id, sessions, from_, to_) -> dict:
    # Cumulative ALL: aggregate only the stores that actually have a POS export,
    # so conversion stays "where it is attributable" — stores without POS are
    # excluded from both numerator and denominator and reported as such.
    if is_all_stores(store_id):
        agg_unique = agg_conv = agg_txn = 0
        for sid in [s for s in {k[0] for k in sessions} if pos_store_id(s)]:
            sub = {k: v for k, v in sessions.items() if k[0] == sid}
            c = _conversion(sid, sub, from_, to_)
            agg_unique += c["unique_visitors"]
            agg_conv += c["converted_visitors"]
            agg_txn += c.get("total_transactions", 0)
        rate = round(min(agg_conv / agg_unique, 1.0), 4) if agg_unique else 0.0
        return {
            "conversion_rate": rate,
            "converted_visitors": agg_conv,
            "unique_visitors": agg_unique,
            "total_transactions": agg_txn,
            "method": "billing_presence_before_txn (cumulative, POS stores only)",
            "evidence": (
                f"{agg_conv}/{agg_unique} visitors at POS-enabled stores were in the billing "
                f"zone within 5 min before one of {agg_txn} POS transactions; stores with no "
                f"POS export are excluded from conversion."
            ),
        }

    customers = _customers(sessions)
    unique = len(customers)
    pos_id = pos_store_id(store_id)
    if not pos_id:
        # No POS export → CV-only "checkout rate": distinct customers who reached
        # the billing area on camera, over footfall. This is observed checkouts,
        # NOT rupee-attributed sales (Store 2 has no POS feed) — the dashboard
        # marks revenue/avg-bill unavailable and shows the checkout count instead.
        checkouts = sum(1 for s in customers if s.billing_ts)
        rate = round(min(checkouts / unique, 1.0), 4) if unique else 0.0
        return {
            "conversion_rate": rate,
            "converted_visitors": checkouts,
            "observed_checkouts": checkouts,
            "unique_visitors": unique,
            "method": "cv_checkout_rate",
            "evidence": (
                f"{checkouts} customer(s) reached the billing area on camera — CV-only "
                f"checkout rate (observed checkouts ÷ footfall). No POS feed for this "
                f"store, so this is not rupee-attributed sales."
            ),
        }

    # The CV clip's wall-clock is read off the on-screen clock and can be minutes
    # off, so the billing-zone presences may not line up with the POS day even
    # though the video shows real billing. We therefore join against ALL of the
    # store's bills and auto-correct a constant clip-clock skew: shift the
    # observed billing presences by the offset that lands their median on the
    # nearest real bill, then credit a visitor as converted if a (shifted)
    # presence falls within 5 min before a bill. (Documented in CHOICES — this is
    # a clock alignment, not invented sales.)
    txns = pos.transactions(pos_id)  # full trading day, not just the clip window
    offset = _billing_offset(pos_id, customers)

    converted: set = set()
    for t_ms, _amt in txns:
        lo = t_ms - CONVERSION_WINDOW_MS
        for s in customers:
            if id(s) in converted:
                continue
            if any(lo <= bt + offset <= t_ms for bt in s.billing_ts):
                converted.add(id(s))
    rate = round(min(len(converted) / unique, 1.0), 4) if unique else 0.0
    skew_min = round(offset / 60000, 1)
    return {
        "conversion_rate": rate,
        "converted_visitors": len(converted),
        "unique_visitors": unique,
        "total_transactions": len(txns),
        "method": "billing_presence_before_txn (clip-clock auto-aligned)",
        "evidence": (
            f"{len(converted)} visitor(s) were at the billing zone within 5 min before one of "
            f"{len(txns)} POS bills (CV billing clip auto-aligned to the POS clock by "
            f"{skew_min:+g} min — the eyeballed clip start was off; see CHOICES)."
        ),
    }


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


def metrics(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    from_, to_ = _window(store_id, from_, to_)
    sessions, events = build_sessions(store_id, from_, to_)
    customers = _customers(sessions)
    # Footfall has TWO co-headline numbers (fragmentation-aware, from occupancy.json):
    #   peak_occupancy = most people on the busiest floor camera at once (robust),
    #   total_visitors = de-fragmented distinct shoppers (estimate).
    # door_entries = entry-line crossings only (clip window); zone_visitors = floor
    # engagement. Conversion divides by total_visitors so the rate is consistent.
    peak_occupancy, total_visitors, staff_count = _occupancy(store_id, events)
    n = total_visitors
    door_entries = sum(1 for s in customers if s.entered)
    zone_visitors = sum(1 for s in customers if s.zones_entered)

    # avg dwell per zone (ms) across customer sessions that visited each zone.
    zone_dwells: Dict[str, List[int]] = defaultdict(list)
    for s in customers:
        for z, d in s.zone_dwell.items():
            if d > 0:
                zone_dwells[z].append(d)
    avg_dwell_per_zone = {
        z: int(sum(v) / len(v)) for z, v in zone_dwells.items() if v
    }
    overall_dwell = [d for v in zone_dwells.values() for d in v]
    avg_dwell_ms = int(sum(overall_dwell) / len(overall_dwell)) if overall_dwell else 0

    # queue depth + abandonment.
    joins = sum(len(s.billing_ts) for s in customers)
    abandons = sum(1 for s in customers if s.abandoned)
    depths = [
        (ev.get("metadata") or {}).get("queue_depth")
        for ev in canonical_store.fetch(store_id, from_, to_, types=["BILLING_QUEUE_JOIN"])
    ]
    depths = [int(d) for d in depths if d is not None]
    abandonment_rate = round(abandons / joins, 4) if joins else 0.0

    conv = _conversion(store_id, sessions, from_, to_)

    # best-effort demographics (non-staff). See CHOICES.md accuracy caveat.
    gender_counts: Dict[str, int] = defaultdict(int)
    age_counts: Dict[str, int] = defaultdict(int)
    for s in customers:
        if s.gender:
            gender_counts[s.gender] += 1
        if s.age_bucket:
            age_counts[s.age_bucket] += 1

    return {
        "store_id": store_id,
        "window": {"from": from_, "to": to_},
        "unique_visitors": n,
        "peak_occupancy": peak_occupancy,
        "total_visitors": total_visitors,
        "door_entries": door_entries,
        "zone_visitors": zone_visitors,
        "staff_excluded": staff_count,
        # Rate uses the in-store footfall as the denominator so it's consistent
        # with the headline (not the raw per-camera session count).
        "conversion_rate": round(min(conv["converted_visitors"] / n, 1.0), 4) if n else 0.0,
        "converted_visitors": conv["converted_visitors"],
        "avg_dwell_ms": avg_dwell_ms,
        "avg_dwell_per_zone_ms": avg_dwell_per_zone,
        "queue_depth_max": max(depths) if depths else 0,
        "abandonment_rate": abandonment_rate,
        "billing_queue_joins": joins,
        "billing_queue_abandons": abandons,
        # Scaled to the footfall headline so the counts never exceed/contradict
        # total_visitors (the sample is tallied across cameras; proportions kept).
        "demographics": {
            "gender": _scale_counts(dict(gender_counts), n),
            "age_bucket": _scale_counts(dict(age_counts), n),
            "note": "best-effort body/VLM estimate on blur-faced footage, scaled to footfall",
        },
        "conversion_method": conv.get("method"),
        "observed_checkouts": conv.get("observed_checkouts"),
        "data_confidence": "low" if n < MIN_SESSIONS_CONFIDENT else "ok",
        "conversion_evidence": conv["evidence"],
    }


def funnel(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    from_, to_ = _window(store_id, from_, to_)
    sessions, events = build_sessions(store_id, from_, to_)
    customers = _customers(sessions)

    # Entry stage = total de-fragmented visitors (the funnel base), not a per-camera recount.
    entered = _occupancy(store_id, events)[1]
    zone_visit = sum(1 for s in customers if s.zones_entered)
    billing_queue = sum(1 for s in customers if s.billing_ts)
    purchase = _conversion(store_id, sessions, from_, to_)["converted_visitors"]

    stages = [
        ("entry", entered),
        ("zone_visit", zone_visit),
        ("billing_queue", billing_queue),
        ("purchase", purchase),
    ]
    out = []
    for i, (name, count) in enumerate(stages):
        prev = stages[i - 1][1] if i else count
        drop = round(1 - (count / prev), 4) if prev else 0.0
        out.append({"stage": name, "count": count, "drop_off": max(drop, 0.0)})

    return {
        "store_id": store_id,
        "window": {"from": from_, "to": to_},
        "stages": out,
        "sessions": entered,
        "data_confidence": "low" if entered < MIN_SESSIONS_CONFIDENT else "ok",
    }


def heatmap(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    from_, to_ = _window(store_id, from_, to_)
    sessions, events = build_sessions(store_id, from_, to_)
    customers = _customers(sessions)
    # Report sessions as the de-fragmented footfall (consistent with the headline),
    # not the larger per-camera session tally.
    _, total_visitors, _ = _occupancy(store_id, events)

    visits: Dict[str, int] = defaultdict(int)
    dwell: Dict[str, List[int]] = defaultdict(list)
    for s in customers:
        for z in s.zones_entered:
            visits[z] += 1
        for z, d in s.zone_dwell.items():
            if d > 0:
                dwell[z].append(d)

    max_visits = max(visits.values()) if visits else 0
    avg_dwell = {z: (sum(v) / len(v)) for z, v in dwell.items() if v}
    max_dwell = max(avg_dwell.values()) if avg_dwell else 0.0

    # Always include the store's known floor zones (even at 0 visits) so the map
    # shows the whole layout — fixes Store 2 hiding left_wall when only right_wall
    # had activity.
    floor = set(floor_cameras(store_id))
    floor_zones = {z for z, meta in _ZONE_BRANDS.items() if meta.get("camera") in floor}

    zones = []
    for z in sorted(set(visits) | set(avg_dwell) | floor_zones):
        zones.append({
            "zone_id": z,
            "visits": visits.get(z, 0),
            "avg_dwell_ms": int(avg_dwell.get(z, 0)),
            "visit_score": round(100 * visits.get(z, 0) / max_visits, 1) if max_visits else 0.0,
            "dwell_score": round(100 * avg_dwell.get(z, 0) / max_dwell, 1) if max_dwell else 0.0,
        })

    return {
        "store_id": store_id,
        "window": {"from": from_, "to": to_},
        "zones": zones,
        "sessions": total_visitors,
        "data_confidence": "low" if total_visitors < MIN_SESSIONS_CONFIDENT else "ok",
    }


def anomalies(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> List[dict]:
    from_, to_ = _window(store_id, from_, to_)
    sessions, events = build_sessions(store_id, from_, to_)
    out: List[dict] = []

    # -- QUEUE_SPIKE -----------------------------------------------------
    depths = [
        (ev.get("metadata") or {}).get("queue_depth")
        for ev in events if ev["event_type"] == "BILLING_QUEUE_JOIN"
    ]
    depths = [int(d) for d in depths if d is not None]
    if depths:
        peak = max(depths)
        if peak >= QUEUE_WARN:
            sev = "CRITICAL" if peak >= QUEUE_CRITICAL else "WARN"
            out.append({
                "type": "QUEUE_SPIKE",
                "severity": sev,
                "observed": peak,
                "threshold": QUEUE_WARN,
                "evidence": f"Billing queue reached depth {peak} (threshold {QUEUE_WARN}).",
                "suggested_action": "Open an additional billing counter to drain the queue.",
            })

    # -- CONVERSION_DROP (vs configured expected; 7-day baseline unavailable) --
    # Uses the same total_visitors denominator as the headline, and fires for the
    # CV-only checkout rate too (Store 2) — not just POS-attributed conversion.
    conv = _conversion(store_id, sessions, from_, to_)
    peak_occ, total_v, _ = _occupancy(store_id, events)
    is_conv = conv["method"].startswith("billing") or conv["method"] == "cv_checkout_rate"
    if is_conv and total_v >= MIN_VISITORS_FOR_CONV:
        rate = round(min(conv["converted_visitors"] / total_v, 1.0), 4) if total_v else 0.0
        if rate < EXPECTED_CONVERSION * 0.6:
            sev = "CRITICAL" if rate < EXPECTED_CONVERSION * 0.3 else "WARN"
            cv = " (CV checkout rate — no POS)" if conv["method"] == "cv_checkout_rate" else ""
            out.append({
                "type": "CONVERSION_DROP",
                "severity": sev,
                "observed": rate,
                "expected": EXPECTED_CONVERSION,
                "evidence": (
                    f"Conversion {rate:.0%}{cv} is below the expected {EXPECTED_CONVERSION:.0%} "
                    f"(no 7-day history available — compared to configured baseline)."
                ),
                "suggested_action": "Review staffing on the floor and at billing for this window.",
            })

    # -- ABANDONMENT_SPIKE (joined the billing queue, then left before paying) --
    custs = _customers(sessions)
    joins = sum(1 for s in custs if s.billing_ts)
    abandons = sum(1 for s in custs if s.abandoned)
    if joins >= MIN_JOINS_FOR_ABANDON:
        share = round(abandons / joins, 2)
        if share >= ABANDON_WARN:
            out.append({
                "type": "ABANDONMENT_SPIKE",
                "severity": "CRITICAL" if share >= ABANDON_CRITICAL else "WARN",
                "observed": share,
                "threshold": ABANDON_WARN,
                "evidence": (
                    f"{abandons} of {joins} billing-queue joins were abandoned "
                    f"({share:.0%}) — shoppers are leaving the queue before paying."
                ),
                "suggested_action": "Open another counter / speed up billing to recover the queue.",
            })

    # -- CROWDING (peak occupancy on the busiest floor camera) --
    if peak_occ >= CROWDING_WARN:
        out.append({
            "type": "CROWDING",
            "severity": "CRITICAL" if peak_occ >= CROWDING_CRITICAL else "WARN",
            "observed": peak_occ,
            "threshold": CROWDING_WARN,
            "evidence": (
                f"Up to {peak_occ} people were on the busiest floor camera at once — "
                f"the floor is getting crowded."
            ),
            "suggested_action": "Add floor staff / manage flow at peak to keep service levels up.",
        })

    # -- DEAD_ZONE (a zone quiet in the trailing 30 min of ITS OWN camera) -----
    # "Recent" is measured per camera, not globally: Store 2's clips aren't time-
    # synced (zone clip ~15:27, entry ~19:39), so a global trailing window wrongly
    # flagged zones whose camera simply recorded earlier. Compare each zone to its
    # own camera's last activity instead — on a short clip nothing is "dead".
    cam_last: Dict[Optional[str], int] = {}
    zone_cam: Dict[str, Optional[str]] = {}
    zone_last: Dict[str, int] = {}
    for ev in events:
        cam = ev.get("camera_id")
        cam_last[cam] = max(cam_last.get(cam, -1), ev["ts_ms"])
        z = ev.get("zone_id")
        if z:
            zone_cam[z] = cam
            zone_last[z] = max(zone_last.get(z, -1), ev["ts_ms"])
    for z in sorted(zone_last):
        cam_now = cam_last.get(zone_cam.get(z))
        if cam_now is not None and zone_last[z] < cam_now - DEAD_ZONE_MS:
            out.append({
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "zone_id": z,
                "evidence": f"Zone {z} had no visits in the last 30 min of its camera's feed.",
                "suggested_action": f"Check stock/signage and the camera feed for {z}.",
            })

    return out


# ---------------------------------------------------------------------------
# Shared helpers for the rich store-aware endpoints below
# ---------------------------------------------------------------------------


def _has_pos(store_id: str) -> bool:
    """True if this store — or the cumulative ALL view (which includes Store 1) — has POS."""
    return is_all_stores(store_id) or bool(pos_store_id(store_id))


def _pos_filter(store_id: str) -> Optional[str]:
    """POS store key to filter bills by; None = all POS rows (the ALL view)."""
    return None if is_all_stores(store_id) else pos_store_id(store_id)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _clip_ref(camera: Optional[str], center_ms: int, pad_s: int = 15) -> dict:
    """Camera + window so a reviewer can pull footage; playable fields when the clip exists."""
    cam = camera or "?"
    lo, hi = center_ms - pad_s * 1000, center_ms + pad_s * 1000
    ref = {
        "camera": cam,
        "from": _iso(lo),
        "to": _iso(hi),
        "review": f"Open {cam} footage around {_iso(center_ms)[11:19]}Z (±{pad_s}s)",
    }
    clip = resolve_clip(cam, ref["from"], ref["to"])
    if clip:
        ref.update(clip)
    return ref


def _peak_entry_hour(store_id, from_, to_) -> Optional[str]:
    counts: Dict[int, int] = defaultdict(int)
    for e in canonical_store.fetch(store_id, from_, to_, types=["ENTRY"]):
        counts[datetime.fromtimestamp(e["ts_ms"] / 1000, tz=IST).hour] += 1
    if not counts:
        return None
    return f"{max(counts, key=lambda h: counts[h]):02d}:00"


# ---------------------------------------------------------------------------
# Live overview — KPI summary + recent events (dashboard home)
# ---------------------------------------------------------------------------


def live(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    # CV metrics use the canonical event window; POS totals use the caller's
    # explicit window, else the full POS day. The two sources have different
    # natural spans (a ~2-min sample clip vs a full trading day), so binding the
    # POS total to the tiny CV window would wrongly report ₹0 revenue.
    win_from, win_to = _window(store_id, from_, to_)
    m = metrics(store_id, from_, to_)

    # No POS feed → revenue/avg-bill are unavailable (None, not ₹0) so the UI can
    # render "— no POS feed" rather than a misleading zero. Store 2 is in this path.
    has_pos = _has_pos(store_id)
    total_revenue = avg_bill = None
    if has_pos:
        bills = pos.get_bills(from_, to_, _pos_filter(store_id))
        nb = len(bills)
        total_revenue = round(sum(b.amount for b in bills), 2)
        avg_bill = round(total_revenue / nb, 2) if nb else 0.0

    evs = canonical_store.fetch(store_id, win_from, win_to)
    recent = [
        {
            "ts": e["ts_iso"],
            "type": e["event_type"],
            "camera": e.get("camera_id"),
            "visitor": e["visitor_id"],
            "zone": e.get("zone_id"),
            "store_id": e["store_id"],
        }
        for e in reversed(evs[-20:])
    ]

    return {
        "store_id": store_id,
        "window": {"from": win_from, "to": win_to},
        "footfall": m["total_visitors"],
        "peak_occupancy": m["peak_occupancy"],
        "total_visitors": m["total_visitors"],
        "door_entries": m["door_entries"],
        "zone_visitors": m["zone_visitors"],
        "staff_count": m["staff_excluded"],
        "conversion_rate": m["conversion_rate"],
        "conversion_method": m["conversion_method"],
        "observed_checkouts": m["observed_checkouts"],
        "has_pos": has_pos,
        "avg_dwell_ms": m["avg_dwell_ms"],
        "queue_depth_max": m["queue_depth_max"],
        "total_revenue": total_revenue,
        "avg_bill_value": avg_bill,
        "peak_hour": _peak_entry_hour(store_id, win_from, win_to),
        "demographics": m["demographics"],
        "recent_events": recent,
        "data_confidence": m["data_confidence"],
    }


# ---------------------------------------------------------------------------
# Brand stands — CV attention (zone dwell, staff-excluded) joined to POS outcome
# ---------------------------------------------------------------------------


def brands(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    win_from, win_to = _window(store_id, from_, to_)  # CV attention window
    sessions, _ = build_sessions(store_id, win_from, win_to)
    customers = _customers(sessions)

    visits_by_zone: Dict[str, int] = defaultdict(int)
    dwell_by_zone: Dict[str, int] = defaultdict(int)
    for s in customers:
        for z in s.zones_entered:
            visits_by_zone[z] += 1
        for z, d in s.zone_dwell.items():
            dwell_by_zone[z] += d
    total_dwell = sum(dwell_by_zone.values()) or 1

    has_pos = _has_pos(store_id)
    breakdown = pos.brand_breakdown_in_window(from_, to_) if has_pos else {}

    names = set(visits_by_zone) | set(dwell_by_zone)
    if has_pos:
        names |= set(_ZONE_BRANDS)  # include shelved-but-unvisited Store 1 stands
    else:
        # No-POS store (Store 2): surface its known floor stands even if unvisited
        # this window so the brand menu isn't empty (matched by floor camera).
        floor = set(floor_cameras(store_id))
        names |= {z for z, meta in _ZONE_BRANDS.items() if meta.get("camera") in floor}

    stands = []
    for name in names:
        meta = _ZONE_BRANDS.get(name, {})
        brand_list = meta.get("brands", [])
        visits = visits_by_zone.get(name, 0)
        dwell_ms = dwell_by_zone.get(name, 0)
        attn_min = dwell_ms / 60000
        revenue = round(sum(breakdown.get(b, {}).get("revenue", 0.0) for b in brand_list), 2)
        units = sum(breakdown.get(b, {}).get("units", 0) for b in brand_list)
        prod: Dict[str, int] = defaultdict(int)
        for b in brand_list:
            for pn, q in breakdown.get(b, {}).get("top_products", []):
                prod[pn] += q
        top = sorted(prod.items(), key=lambda x: -x[1])[:3]
        share = round(dwell_ms / total_dwell, 3)
        stands.append({
            "stand": name,
            "label": meta.get("label") or name.replace("_", " ").title(),
            "camera": meta.get("camera"),
            "brands": brand_list,
            "visits": visits,
            "attention_seconds": round(dwell_ms / 1000, 1),
            "attention_share": share,
            "revenue": revenue,
            "units": units,
            "revenue_per_visit": round(revenue / visits, 2) if visits else 0.0,
            "revenue_per_attention_min": round(revenue / attn_min, 2) if attn_min else 0.0,
            "top_products": [{"product": n, "units": q} for n, q in top],
            "signal": _signal(share, revenue, visits),
        })
    stands.sort(key=lambda s: -s["attention_seconds"])

    return {
        "store_id": store_id,
        "window": {"from": win_from, "to": win_to},
        "count": len(stands),
        "stands": stands,
        "data_confidence": "low" if len(customers) < MIN_SESSIONS_CONFIDENT else "ok",
        "note": None if has_pos else "No POS export for this store — attention only, no revenue.",
    }


# ---------------------------------------------------------------------------
# Customer segments — CV shopping party + POS basket (privacy-preserving)
# ---------------------------------------------------------------------------


def customers(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    win_from, win_to = _window(store_id, from_, to_)  # CV shopping-party window
    sessions, _ = build_sessions(store_id, win_from, win_to)
    custs = _customers(sessions)

    # Party size is only known for shoppers the ENTRY camera grouped; floor-only
    # shoppers carry no group_size and must NOT be assumed solo (that inflated the
    # count to all-solo). Count solo/group over entry-detected parties only.
    parties = [s for s in custs if s.group is not None]
    solo = sum(1 for s in parties if s.group <= 1)
    group = sum(1 for s in parties if s.group >= 2)
    party_total = len(parties)

    has_pos = _has_pos(store_id)
    bills = pos.get_bills(from_, to_, _pos_filter(store_id)) if has_pos else []
    cust_bills = Counter(b.customer_number for b in bills if b.customer_number)
    unique_customers = len(cust_bills)
    repeat_customers = sum(1 for _, c in cust_bills.items() if c > 1)

    n = len(bills)
    avg_items = round(sum(b.items for b in bills) / n, 2) if n else 0.0
    avg_value = round(sum(b.amount for b in bills) / n, 2) if n else 0.0
    multi = sum(1 for b in bills if len(b.brands) > 1)
    single = sum(1 for b in bills if len(b.brands) == 1)
    avg_brands = round(sum(len(b.brands) for b in bills) / n, 2) if n else 0.0

    return {
        "store_id": store_id,
        "window": {"from": win_from, "to": win_to},
        "shopping_party": {
            "solo": solo,
            "group": group,
            "entry_detected": party_total,
            "group_rate": round(group / party_total, 3) if party_total else 0.0,
            "basis": "entry-detected parties (CV, entrance camera) — staff excluded",
        },
        "customers": {
            "unique": unique_customers,
            "repeat": repeat_customers,
            "repeat_rate": round(repeat_customers / unique_customers, 3) if unique_customers else 0.0,
            "basis": "POS customer_number within the window",
        },
        "basket": {
            "bills": n,
            "avg_items_per_bill": avg_items,
            "avg_value_per_bill": avg_value,
            "single_brand_bills": single,
            "multi_brand_bills": multi,
            "avg_brands_per_bill": avg_brands,
        },
        "note": (
            None if has_pos
            else "No POS export for this store — basket/repeat metrics unavailable; "
                 "shopping party is CV-only."
        ),
    }


# ---------------------------------------------------------------------------
# Investigation — loss-prevention review prompts (behavioural, identity-free)
# ---------------------------------------------------------------------------

_INV_BUCKET_MS = 5 * 60 * 1000
_DWELL_FLOOR_MS = 60_000
_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}
# Unbilled-cash review fires only on a meaningful excess of counter approaches
# over matched bills (an approach is not a purchase, so small gaps are normal).
_UNBILLED_MIN, _UNBILLED_CRITICAL = 3, 5


def investigation(store_id: str, from_: Optional[str] = None, to_: Optional[str] = None) -> dict:
    from_, to_ = _window(store_id, from_, to_)
    sessions, events = build_sessions(store_id, from_, to_)
    incidents: List[dict] = []

    # 1) Billing review — for POS stores, cash approaches not matched by a bill
    #    (possible unbilled exit); for no-POS stores (Store 2) we cannot reconcile
    #    against sales, so each billing burst is an info prompt to review the clip.
    # Align billing approaches to the POS clock (the same skew conversion corrects)
    # before bucketing them against bills, so a real sale isn't mislabelled
    # "unbilled" just because the cam5 clock is offset. No-POS stores keep offset 0.
    offset = _billing_offset(_pos_filter(store_id), _customers(sessions)) if _has_pos(store_id) else 0
    joins_by_bucket: Dict[int, List[int]] = defaultdict(list)
    cam_by_bucket: Dict[int, str] = {}
    for ev in events:
        if ev["event_type"] == "BILLING_QUEUE_JOIN":
            b = (ev["ts_ms"] + offset) // _INV_BUCKET_MS
            joins_by_bucket[b].append(ev["ts_ms"])  # raw ts kept for the clip pointer
            cam_by_bucket[b] = ev.get("camera_id") or "cam5"
    if _has_pos(store_id) and not is_all_stores(store_id):
        # Tie the unbilled check to the conversion join (clock-aligned, full POS
        # day) rather than per-5-min-bucket matching, which produced alarmist
        # noise on the ~2-min cam5 clip: of the distinct customers who reached the
        # billing zone, how many did NOT match a bill. One honest review prompt,
        # only on a meaningful excess — an approach is not necessarily a purchase.
        custs = _customers(sessions)
        billing_visitors = sum(1 for s in custs if s.billing_ts)
        converted = _conversion(store_id, sessions, from_, to_)["converted_visitors"]
        unmatched = billing_visitors - converted
        if unmatched >= _UNBILLED_MIN and joins_by_bucket:
            stamps = sorted(bt for s in custs for bt in s.billing_ts)
            cam = next(iter(cam_by_bucket.values()), "cam5")
            center = stamps[len(stamps) // 2]
            incidents.append({
                "kind": "unbilled_cash_approach",
                "severity": "critical" if unmatched >= _UNBILLED_CRITICAL else "warning",
                "camera": cam,
                "ts": _iso(center),
                "window": {"from": _iso(stamps[0]), "to": _iso(stamps[-1])},
                "evidence": (
                    f"{billing_visitors} customers reached the cash counter but only {converted} "
                    f"matched a POS bill ({unmatched} unmatched, clock-aligned). Review the footage "
                    f"for unbilled exits — note not every counter approach is a purchase."
                ),
                "clip_ref": _clip_ref(cam, center),
            })
    elif not _has_pos(store_id):
        for b, stamps in sorted(joins_by_bucket.items()):
            cam, center = cam_by_bucket[b], min(stamps)
            incidents.append({
                "kind": "billing_without_pos",
                "severity": "info",
                "camera": cam,
                "ts": _iso(center),
                "window": {"from": _iso(b * _INV_BUCKET_MS), "to": _iso((b + 1) * _INV_BUCKET_MS)},
                "evidence": (
                    f"{len(stamps)} customer(s) reached the billing area in this 5-min window. "
                    f"No POS feed for this store — open the clip to confirm the sale."
                ),
                "clip_ref": _clip_ref(cam, center),
            })

    # 2) Long unattended dwell — customer lingering well beyond normal.
    for s in _customers(sessions):
        if s.first_ms is None or s.last_ms is None:
            continue
        dwell = s.last_ms - s.first_ms
        if dwell < _DWELL_FLOOR_MS:
            continue
        zones = ", ".join(sorted(s.zones_entered)) or "—"
        incidents.append({
            "kind": "long_unattended_dwell",
            "severity": "info",
            "camera": s.last_cam or "?",
            "ts": _iso(s.last_ms),
            "window": {"from": _iso(s.first_ms), "to": _iso(s.last_ms)},
            "evidence": (
                f"Customer dwelled {dwell / 1000:.0f}s (zones: {zones}) — well above normal. "
                f"Review for concealment / tampering."
            ),
            "clip_ref": _clip_ref(s.last_cam, s.last_ms),
        })

    incidents.sort(key=lambda i: (_SEV_RANK.get(i["severity"], 9), i["ts"]))
    return {
        "store_id": store_id,
        "window": {"from": from_, "to": to_},
        "count": len(incidents),
        "kinds_available": [
            "unbilled_cash_approach", "billing_without_pos", "long_unattended_dwell",
        ],
        "incidents": incidents,
        "note": "Review prompts, not accusations — no identity/biometrics stored.",
    }
