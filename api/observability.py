"""
Structured logging + per-request instrumentation.

Phase 3 scope: JSON logs to stdout and a request-id middleware that binds a
ULID to each request, logs a one-line summary on completion (method, path,
status, duration_ms), and echoes it back as the ``X-Request-Id`` header.

The Prometheus middleware + /internal/metrics endpoint land in Phase 8; this
module is intentionally limited to logging for now.
"""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from ulid import ULID

logger = structlog.get_logger()


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
