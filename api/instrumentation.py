"""
Prometheus metric definitions — shared across the API.

Kept in its own module (no FastAPI/Starlette imports) so services like
event_store and anomaly_detect can increment counters without importing the
web layer or risking circular imports. The /internal/metrics route exposes the
default registry via ``generate_latest``.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# --- HTTP request metrics (set by PrometheusMiddleware) ---

api_requests_total = Counter(
    "api_requests_total",
    "Total API requests.",
    ["endpoint", "method", "status"],
)

api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "API request latency in seconds.",
    ["endpoint", "method"],
)

# --- domain metrics ---

events_processed_total = Counter(
    "events_processed_total",
    "Total events parsed into the store across (re)loads.",
)

events_in_store = Gauge(
    "events_in_store",
    "Number of events currently loaded in the in-memory store.",
)

# Point-in-time count of anomalies currently present in the loaded dataset,
# per kind. A Gauge (not a Counter): detection is a pure, query-driven function
# of the static event store, so this is computed once at startup over the full
# window — it reflects the DATA, not request traffic. (Counting per /anomaly
# call would just measure dashboard poll frequency.) Recompute it anywhere
# store.load() is re-triggered (e.g. a future /replay). Named *_current, not
# *_total, because Prometheus reserves the _total suffix for counters.
anomalies_current = Gauge(
    "anomalies_current",
    "Anomalies currently detected in the loaded dataset, by kind.",
    ["kind"],
)
