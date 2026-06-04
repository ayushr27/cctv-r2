"""
Canonical event schema — the Purplle Tech Challenge "Required Output Schema".

This is the contract the scoring harness validates: it is the shape that
``POST /events/ingest`` accepts/stores and that the ``GET /stores/{id}/*``
endpoints read. It is DELIBERATELY DISTINCT from the legacy internal envelope in
``events.py`` (dotted ``visit.*`` types) which still backs the original
dashboard endpoints — the two layers coexist (see CHOICES.md).

Mirrored verbatim as ``worker/canonical_schema.py`` (the worker emits these);
the worker (flat modules) and api (package) cannot share a sys.path, so the
file is duplicated, matching the existing schemas.py/events.py mirror.

Required fields (PDF §4):
  event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id,
  dwell_ms, is_staff, confidence, metadata{queue_depth, sku_zone, session_seq}

event_type catalogue:
  ENTRY · EXIT · ZONE_ENTER · ZONE_EXIT · ZONE_DWELL ·
  BILLING_QUEUE_JOIN · BILLING_QUEUE_ABANDON · REENTRY
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, TypeAdapter, field_serializer

EventType = (
    "ENTRY",
    "EXIT",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "ZONE_DWELL",
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
    "REENTRY",
)
EVENT_TYPES = frozenset(EventType)

# Events that mark a point in time (no accumulated dwell). The rest
# (ZONE_EXIT, ZONE_DWELL, BILLING_QUEUE_ABANDON) carry a dwell_ms > 0.
INSTANTANEOUS = frozenset(
    {"ENTRY", "EXIT", "REENTRY", "ZONE_ENTER", "BILLING_QUEUE_JOIN"}
)


class EventMetadata(BaseModel):
    # Tolerate vendor-specific extras — the provided sample_events.jsonl carries
    # several keys (zone_name, zone_type, is_revenue_zone, zone_hotspot_*) that
    # we keep rather than reject, so ingested third-party events round-trip.
    model_config = {"extra": "allow"}

    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None
    # Best-effort demographics (populated on ENTRY). Faces are blurred in the
    # footage, so these are body/VLM estimates — see the accuracy caveat in
    # CHOICES.md. Optional so non-ENTRY events and external feeds stay valid.
    gender_pred: Optional[str] = None
    age_pred: Optional[int] = None
    age_bucket: Optional[str] = None
    is_face_hidden: Optional[bool] = None
    # Grouping + re-entry provenance.
    group_id: Optional[str] = None
    group_size: Optional[int] = None
    reentry_of: Optional[str] = None  # visitor_id this REENTRY re-associates to


class CanonicalEvent(BaseModel):
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str  # validated against EVENT_TYPES below
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float = 1.0
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    def model_post_init(self, _ctx) -> None:  # noqa: D401
        if self.event_type not in EVENT_TYPES:
            raise ValueError(
                f"event_type {self.event_type!r} not in catalogue {sorted(EVENT_TYPES)}"
            )

    @field_serializer("timestamp")
    def _serialize_ts_utc(self, dt: datetime) -> str:
        """Always emit ISO-8601 UTC with a trailing Z (PDF requirement)."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


CANONICAL_ADAPTER: TypeAdapter = TypeAdapter(CanonicalEvent)


def to_dict(ev: CanonicalEvent) -> dict:
    """Plain JSON-able dict with the UTC-Z timestamp serialization applied."""
    return ev.model_dump(mode="json")
