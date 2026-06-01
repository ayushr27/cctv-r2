"""
Structured logging + per-request instrumentation.

* configure_logging() — structlog JSON to stdout (timestamp, level, logger,
  request_id, and any bound contextvars).
* RequestIdMiddleware — ULID per request, bound to contextvars, echoed as the
  ``X-Request-Id`` header, with a one-line request summary logged on completion.
* PrometheusMiddleware — increments api_requests_total{endpoint,method,status}
  and observes api_request_duration_seconds, labelled by the matched route
  TEMPLATE (e.g. "/events") rather than the raw path, to bound cardinality.
"""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from ulid import ULID

from instrumentation import api_request_duration_seconds, api_requests_total

logger = structlog.get_logger()


def _route_template(request: Request) -> str:
    """The matched route pattern (e.g. /events), or the raw path if unmatched."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def configure_logging() -> None:
    """Emit JSON logs to stdout, with ISO timestamps and bound contextvars."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign a request id, log the request summary, set X-Request-Id."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(ULID())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status = 500
        response = None
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                query=request.url.query or None,
                status=status,
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Count requests and observe latency, labelled by route template."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            endpoint = _route_template(request)
            elapsed = time.perf_counter() - start
            api_requests_total.labels(
                endpoint=endpoint, method=request.method, status=str(status)
            ).inc()
            api_request_duration_seconds.labels(
                endpoint=endpoint, method=request.method
            ).observe(elapsed)
