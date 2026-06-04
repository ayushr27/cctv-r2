import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from observability import (
    PrometheusMiddleware,
    RequestIdMiddleware,
    configure_logging,
)
from routes.anomaly import router as anomaly_router
from routes.brands import router as brands_router
from routes.clip import router as clip_router
from routes.customers import router as customers_router
from routes.events import router as events_router
from routes.funnel import router as funnel_router
from routes.investigation import router as investigation_router
from routes.metrics import router as metrics_router
from routes.stores import router as stores_router
from routes.zones import router as zones_router
from services.anomaly_detect import refresh_anomaly_gauge
from services.canonical_store import StoreUnavailable, canonical_store, parse_utc_ms
from services.event_store import store
from services.pos_join import pos

# A feed whose newest event is older than this (vs wall-clock) is STALE (PDF).
STALE_FEED_MS = 10 * 60 * 1000

configure_logging()
logger = structlog.get_logger()

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    n = store.load()
    b = pos.load()
    # Canonical (PDF-contract) store: seeded from events/canonical.seed.jsonl,
    # then grown by POST /events/ingest.
    c = canonical_store.load()
    # Compute the point-in-time anomaly gauge once over the full dataset.
    anomaly_count = refresh_anomaly_gauge(store, pos)
    logger.info("startup_complete", events_loaded=n, source=store.source,
                bills_loaded=b, pos_source=pos.source, anomalies=anomaly_count,
                canonical_events=c, canonical_seed=canonical_store.seed_source)
    yield


app = FastAPI(title="Store Intelligence API", version="0.1.0", lifespan=lifespan)

# CORS: the dashboard runs on a different origin (localhost:3000 in dev,
# *.vercel.app in deploy) and fetches this API from the browser, so without
# these headers the browser blocks every request. Origins come from
# ALLOWED_ORIGINS (comma-separated); dev default is the local dashboard.
_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)
app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestIdMiddleware)

app.include_router(metrics_router)
app.include_router(events_router)
app.include_router(funnel_router)
app.include_router(zones_router)
app.include_router(anomaly_router)
app.include_router(investigation_router)
app.include_router(brands_router)
app.include_router(customers_router)
app.include_router(clip_router)
app.include_router(stores_router)


@app.exception_handler(StoreUnavailable)
async def _store_unavailable_handler(request: Request, exc: StoreUnavailable):
    """Graceful degradation: the store isn't loaded → structured 503, no stack trace."""
    logger.warning("store_unavailable", path=request.url.path, detail=str(exc))
    return JSONResponse(
        status_code=503,
        content={"error": "store_unavailable", "detail": str(exc), "status_code": 503},
    )


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    """Never leak a raw stack trace in a response body (PDF Part C)."""
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "status_code": 500},
    )


@app.get("/health")
def health():
    """
    Service status + per-store feed freshness. ``STALE_FEED`` fires when a store's
    newest event lags wall-clock by more than 10 min — what an on-call engineer
    checks first. (The committed seed is historical footage, so seeded stores read
    as stale until live events are ingested; the lag is reported transparently.)
    """
    now_ms = int(time.time() * 1000)
    per_store = {}
    stale_feeds = []
    try:
        last = canonical_store.last_ts_per_store()
    except StoreUnavailable:
        last = {}
    for sid, iso in last.items():
        try:
            lag = int((now_ms - parse_utc_ms(iso)) // 1000)
        except Exception:  # noqa: BLE001
            lag = None
        is_stale = lag is not None and lag * 1000 > STALE_FEED_MS
        per_store[sid] = {"last_event": iso, "lag_seconds": lag, "stale": is_stale}
        if is_stale:
            stale_feeds.append(sid)
    return {
        "status": "ok",
        "version": app.version,
        "uptime_seconds": int(time.time() - _start_time),
        "events_loaded": store.loaded,
        "canonical_events": canonical_store.loaded,
        "stores": per_store,
        "stale_feeds": stale_feeds,
        "warning": "STALE_FEED" if stale_feeds else None,
    }


@app.get("/internal/metrics")
def internal_metrics():
    """Prometheus exposition format (scraped by the optional prometheus service)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
