"""GET /funnel?from=&to=&granularity=hour|day — the 5-stage retail funnel.

With granularity=hour, also returns a by_hour array of per-hour stage counts.
Defaults to the union of event + POS ranges when from/to are omitted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from services.funnel import compute_funnel
from services.window import resolve_window

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))


def _hour_slices(from_: str, to: str):
    """Yield (label, hour_from_iso, hour_to_iso) covering [from_, to] by IST hour."""
    start = datetime.fromisoformat(from_).astimezone(IST).replace(minute=0, second=0, microsecond=0)
    end = datetime.fromisoformat(to).astimezone(IST)
    cur = start
    while cur <= end:
        nxt = cur + timedelta(hours=1)
        yield cur.strftime("%H:00"), cur.isoformat(), nxt.isoformat()
        cur = nxt


@router.get("/funnel")
def get_funnel(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    granularity: str = Query("hour", pattern="^(hour|day)$"),
):
    win_from, win_to = resolve_window(from_, to)
    result = compute_funnel(win_from, win_to)
    result["window"] = {"from": win_from, "to": win_to}
    result["granularity"] = granularity

    if granularity == "hour" and win_from and win_to:
        by_hour = []
        for label, h_from, h_to in _hour_slices(win_from, win_to):
            f = compute_funnel(h_from, h_to)
            # only include hours with any activity
            if any(s["count"] for s in f["stages"]) or f["raw_counts"]["billed"]:
                by_hour.append({"hour": label, "stages": f["stages"]})
        result["by_hour"] = by_hour

    return result
