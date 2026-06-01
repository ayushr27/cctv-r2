import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from observability import RequestIdMiddleware, configure_logging
from routes.anomaly import router as anomaly_router
from routes.events import router as events_router
from routes.funnel import router as funnel_router
from routes.metrics import router as metrics_router
from routes.zones import router as zones_router
from services.event_store import store
from services.pos_join import pos

configure_logging()
logger = structlog.get_logger()

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    n = store.load()
    b = pos.load()
    logger.info("startup_complete", events_loaded=n, source=store.source,
                bills_loaded=b, pos_source=pos.source)
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
app.add_middleware(RequestIdMiddleware)

app.include_router(metrics_router)
app.include_router(events_router)
app.include_router(funnel_router)
app.include_router(zones_router)
app.include_router(anomaly_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": int(time.time() - _start_time),
        "events_loaded": store.loaded,
    }
