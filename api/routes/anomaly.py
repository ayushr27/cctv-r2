"""GET /anomaly?since=&kinds= — run the detector registry over a window.

``since`` is the lower bound (default: start of available data). The upper
bound is the latest timestamp across events + POS ("now" for this dataset).
``kinds`` is an optional comma-separated filter (e.g. kinds=zone_starvation).
Results are sorted by severity (critical>warning>info) then time.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from services.anomaly_detect import DETECTORS, run_detectors
from services.event_store import store
from services.pos_join import pos
from services.window import resolve_window

router = APIRouter()


@router.get("/anomaly")
def get_anomaly(
    since: Optional[str] = Query(None, description="Lower time bound (ISO-8601)"),
    kinds: Optional[str] = Query(None, description="Comma-separated detector kinds"),
):
    # since -> from; "now" -> the upper end of the available data range.
    win_from, win_to = resolve_window(since, None)
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None

    anomalies = run_detectors(store, pos, win_from, win_to, kind_list)

    return {
        "window": {"from": win_from, "to": win_to},
        "kinds_available": [d.kind for d in DETECTORS],
        "count": len(anomalies),
        "anomalies": anomalies,
    }
