"""GET /zones?from=&to= — per-zone visit + dwell stats + brand sales.

Zone visit/dwell stats are derived from observed events (the ``zone`` field of
visit.entered_zone). Each zone is also mapped to the POS brands physically
shelved there (api/zone_brands.json, mirrored from worker/zones.json), so the
endpoint reports **zone footfall alongside the brand revenue sold from that
zone** — the closest honest link between CV engagement and POS sales without
cross-camera identity.

conversion_proxy = (visits whose visit_id also has a visit.approached_cash) /
visits. Zone events (cam1/cam2) and cash events (cam5) carry different
per-camera visit_ids (no cross-camera ReID), so this proxy is near-zero by
design; the brand-revenue join is the more meaningful zone<->sales signal.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Query

from services.event_store import store
from services.pos_join import pos
from services.window import resolve_window

router = APIRouter()

# Zone -> {camera, brands[]} map, mirrored from worker/zones.json at build time.
_ZONE_BRANDS_PATH = os.path.join(os.path.dirname(__file__), "..", "zone_brands.json")
try:
    with open(_ZONE_BRANDS_PATH) as f:
        _ZONE_BRANDS = json.load(f).get("zones", {})
except FileNotFoundError:
    _ZONE_BRANDS = {}


@router.get("/zones")
def get_zones(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    win_from, win_to = resolve_window(from_, to)

    entered = store.get_payloads("visit.entered_zone", win_from, win_to)
    exited = store.get_payloads("visit.exited_zone", win_from, win_to)
    cash_visits = {
        p["visit_id"] for p in store.get_payloads("visit.approached_cash", win_from, win_to)
    }

    zone_visits: dict[str, set] = defaultdict(set)
    for p in entered:
        zone_visits[p["zone"]].add(p["visit_id"])

    zone_dwell: dict[str, list] = defaultdict(list)
    for p in exited:
        zone_dwell[p["zone"]].append(p.get("dwell_ms", 0))

    # POS brand revenue for the same window, joined to zones by the brand map.
    brand_rev = pos.brand_revenue_in_window(win_from, win_to)

    # report every zone we saw events for, plus any mapped zone (so a zone with
    # brand sales but no detected footfall still shows up).
    names = set(zone_visits) | set(zone_dwell) | set(_ZONE_BRANDS)
    zones = []
    for name in sorted(names):
        visits = zone_visits.get(name, set())
        dwells = zone_dwell.get(name, [])
        total_dwell_ms = sum(dwells)
        n_visits = len(visits)
        converted = len(visits & cash_visits)

        brands = _ZONE_BRANDS.get(name, {}).get("brands", [])
        zone_revenue = round(sum(brand_rev.get(b, 0.0) for b in brands), 2)

        zones.append(
            {
                "name": name,
                "camera": _ZONE_BRANDS.get(name, {}).get("camera"),
                "visits": n_visits,
                "total_dwell_seconds": round(total_dwell_ms / 1000, 1),
                "avg_dwell_seconds": round(total_dwell_ms / 1000 / len(dwells), 1) if dwells else 0.0,
                "conversion_proxy": round(converted / n_visits, 3) if n_visits else 0.0,
                "brands": brands,
                "brand_revenue": zone_revenue,
            }
        )

    return {
        "window": {"from": win_from, "to": win_to},
        "zones": zones,
        "note": (
            "brand_revenue = POS sales (same window) for the brands shelved in "
            "that zone, from the floor-plan zone<->brand map. conversion_proxy "
            "links zone visit_ids to cash visit_ids and is near-zero (per-camera "
            "identity, no cross-camera ReID)."
        ),
    }
