"""GET /zones?from=&to= — per-zone visit + dwell stats.

Zone names are derived from the observed events (the ``zone`` field of
visit.entered_zone), so the endpoint reflects what was actually seen rather
than depending on the worker's zones.json (which lives outside the api build
context).

conversion_proxy = (visits to this zone whose visit_id also has a
visit.approached_cash) / visits. Because zone events (cam1/cam2) and cash
events (cam5) carry different per-camera visit_ids with no cross-camera
identity, this proxy is structurally near-zero in this multi-camera setup; we
report it honestly and note the limitation in the response rather than faking
a cross-camera link.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Query

from services.event_store import store
from services.window import resolve_window

router = APIRouter()


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

    # visits per zone (distinct visit_ids that entered the zone)
    zone_visits: dict[str, set] = defaultdict(set)
    for p in entered:
        zone_visits[p["zone"]].add(p["visit_id"])

    # dwell per zone (list of dwell_ms) from exited_zone events
    zone_dwell: dict[str, list] = defaultdict(list)
    for p in exited:
        zone_dwell[p["zone"]].append(p.get("dwell_ms", 0))

    zones = []
    for name in sorted(zone_visits.keys() | zone_dwell.keys()):
        visits = zone_visits.get(name, set())
        dwells = zone_dwell.get(name, [])
        total_dwell_ms = sum(dwells)
        n_visits = len(visits)
        converted = len(visits & cash_visits)
        zones.append(
            {
                "name": name,
                "visits": n_visits,
                "total_dwell_seconds": round(total_dwell_ms / 1000, 1),
                "avg_dwell_seconds": round(total_dwell_ms / 1000 / len(dwells), 1) if dwells else 0.0,
                "conversion_proxy": round(converted / n_visits, 3) if n_visits else 0.0,
            }
        )

    return {
        "window": {"from": win_from, "to": win_to},
        "zones": zones,
        "note": (
            "conversion_proxy links zone visit_ids to cash visit_ids; with "
            "per-camera identity (no cross-camera ReID) it is near-zero by design."
        ),
    }
