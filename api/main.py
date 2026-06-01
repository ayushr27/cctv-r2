import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from observability import RequestIdMiddleware, configure_logging
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
app.add_middleware(RequestIdMiddleware)

app.include_router(metrics_router)
app.include_router(events_router)
app.include_router(funnel_router)
app.include_router(zones_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": int(time.time() - _start_time),
        "events_loaded": store.loaded,
    }
