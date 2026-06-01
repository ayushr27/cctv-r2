"""GET /metrics?from=&to= — store-wide KPIs computed from the event store + POS.

All values are computed live from the loaded data and vary with the from/to
window (the integrity requirement). When from/to are omitted the window
defaults to the union of the event range and the POS range (see services.window).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from schemas.responses import MetricsResponse
from services.event_store import store
from services.pos_join import pos
from services.window import resolve_window

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    win_from, win_to = resolve_window(from_, to)

    # footfall = unique customer visits. Footfall is owned by the entrance
    # camera, so count visit.entered (staff exclusion arrives in Phase 5).
    entered = store.get_payloads("visit.entered", win_from, win_to)
    footfall = len({p["visit_id"] for p in entered}) if entered else 0

    # unique_groups = distinct group_id (a null group is its own group).
    groups = set()
    for i, p in enumerate(entered):
        gid = p.get("group_id")
        groups.add(gid if gid else f"__solo_{p.get('visit_id', i)}")
    unique_groups = len(groups)

    # peak_hour = IST hour with the most entries.
    hist = store.hour_histogram("visit.entered", win_from, win_to)
    peak_hour = max(hist, key=hist.get) if hist else None

    # avg_dwell_seconds = mean of visit.ended.total_dwell_ms / 1000.
    visits = store.get_visits(win_from, win_to)
    dwell_ms = [v.get("total_dwell_ms", 0) for v in visits]
    avg_dwell_seconds = round(sum(dwell_ms) / len(dwell_ms) / 1000, 2) if dwell_ms else 0.0

    # POS-derived: revenue + conversion (time-bucket join against footfall).
    total_revenue, avg_bill_value, _ = pos.revenue_in_window(win_from, win_to)
    # entered payloads need a ts for bucketing; fetch full events for that.
    entered_events = store.get_events(win_from, win_to, type_="visit.entered", limit=1000)
    conv = pos.conversion_in_window(entered_events, win_from, win_to)

    return MetricsResponse(
        window={"from": win_from, "to": win_to},
        footfall=footfall,
        unique_groups=unique_groups,
        peak_hour=peak_hour,
        avg_dwell_seconds=avg_dwell_seconds,
        conversion_rate=conv["conversion_rate"],
        avg_bill_value=avg_bill_value,
        total_revenue=total_revenue,
    )
