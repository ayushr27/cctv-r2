"""
PDF-contract endpoints: ingest + per-store intelligence.

  POST /events/ingest                      batch ≤500, idempotent, partial success
  GET  /stores/{store_id}/metrics          unique visitors, conversion, dwell, queue
  GET  /stores/{store_id}/funnel           Entry→Zone→Billing→Purchase + drop-off
  GET  /stores/{store_id}/heatmap          per-zone freq + dwell, normalized 0–100
  GET  /stores/{store_id}/anomalies        QUEUE_SPIKE / CONVERSION_DROP / DEAD_ZONE

All reads are store-agnostic and zero-traffic safe: an unknown or empty store
returns 200 with zeroed fields (never 404/null), so the acceptance gate's
``GET /stores/STORE_BLR_002/metrics`` always returns valid JSON. If the store
was never loaded, queries raise ``StoreUnavailable`` → structured HTTP 503.
"""

from __future__ import annotations

from typing import List, Optional, Union

import structlog
from fastapi import APIRouter, Body, Query

from services import intelligence
from services.canonical_store import canonical_store

router = APIRouter()

MAX_BATCH = 500


@router.post("/events/ingest")
def ingest_events(
    payload: Union[List[dict], dict] = Body(...),
):
    """
    Accept a batch of events (a JSON array, or ``{"events": [...]}``). Validates +
    deduplicates + stores. Idempotent by ``event_id``; malformed rows are reported
    individually under ``rejected`` (partial success) — the call never returns 5xx
    for bad event data, only for an unavailable store.
    """
    if isinstance(payload, dict):
        events = payload.get("events", [])
    else:
        events = payload

    if not isinstance(events, list):
        return _error(400, "events must be a list or {'events': [...]}")
    # event_count surfaces in the structured request log (PDF Part C).
    structlog.contextvars.bind_contextvars(event_count=len(events))
    if len(events) > MAX_BATCH:
        return _error(
            413,
            f"batch of {len(events)} exceeds the {MAX_BATCH}-event limit",
            received=len(events),
        )

    result = canonical_store.ingest(events)
    # 200 even with some rejected rows (partial success); 207-style body.
    return {"status": "ok", **result}


@router.get("/stores/{store_id}/metrics")
def store_metrics(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    return intelligence.metrics(store_id, from_, to)


@router.get("/stores/{store_id}/funnel")
def store_funnel(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    return intelligence.funnel(store_id, from_, to)


@router.get("/stores/{store_id}/heatmap")
def store_heatmap(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    return intelligence.heatmap(store_id, from_, to)


@router.get("/stores/{store_id}/anomalies")
def store_anomalies(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="alias for ?from="),
):
    anomalies = intelligence.anomalies(store_id, from_ or since, to)
    return {"store_id": store_id, "anomalies": anomalies, "count": len(anomalies)}


# -- rich store-aware views (the dashboard's Live / Brands / Customers /
#    Investigation pages, now one store-parameterised path with an ALL view) --


@router.get("/stores/{store_id}/live")
def store_live(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    return intelligence.live(store_id, from_, to)


@router.get("/stores/{store_id}/brands")
def store_brands(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    return intelligence.brands(store_id, from_, to)


@router.get("/stores/{store_id}/customers")
def store_customers(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    return intelligence.customers(store_id, from_, to)


@router.get("/stores/{store_id}/investigation")
def store_investigation(
    store_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="alias for ?from="),
):
    return intelligence.investigation(store_id, from_ or since, to)


# Helper kept local so the contract module owns its error shape.
def _error(status: int, message: str, **extra):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status,
        content={"error": message, "status_code": status, **extra},
    )
