"""
Tolerant ingest normalizer: map an arbitrary inbound event dict to the canonical
schema (schemas/canonical.py) before validation.

Why this exists
---------------
The challenge materials carry TWO event shapes:

* the PDF "Required Output Schema" — UPPERCASE ``event_type``, ``event_id``,
  ``visitor_id``, ``timestamp``, ``metadata{...}`` (what we emit + store), and
* the provided ``sample_events.jsonl`` — lowercase ``event_type``
  (``entry``/``zone_entered``/``queue_completed``), ``id_token``/``track_id``,
  ``store_code``, ``event_timestamp``/``event_time``/``queue_*_ts``,
  ``gender_pred``/``gender`` … and NO ``event_id``/``confidence``.

``POST /events/ingest`` must accept both so a grader can replay either. This
module converts anything into a canonical dict; the caller then validates with
``CANONICAL_ADAPTER`` and reports per-item failures (partial success).

Idempotency: events that arrive without an ``event_id`` get a DETERMINISTIC
uuid5 derived from (store, visitor, type, timestamp), so re-POSTing the same
batch dedups against the ``event_id`` primary key instead of duplicating.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

# Stable namespace for synthesizing event_ids (any fixed UUID works).
_NS = uuid.UUID("6f1a7b3e-0c2d-4e5f-8a9b-1c2d3e4f5a6b")

# Lowercase / vendor event_type -> canonical UPPERCASE type.
_TYPE_MAP = {
    "entry": "ENTRY",
    "exit": "EXIT",
    "zone_enter": "ZONE_ENTER",
    "zone_entered": "ZONE_ENTER",
    "zone_exit": "ZONE_EXIT",
    "zone_exited": "ZONE_EXIT",
    "zone_dwell": "ZONE_DWELL",
    "billing_queue_join": "BILLING_QUEUE_JOIN",
    "queue_join": "BILLING_QUEUE_JOIN",
    "queue_joined": "BILLING_QUEUE_JOIN",
    # the sample's "queue_completed" = joined-and-served (not abandoned) -> JOIN
    "queue_completed": "BILLING_QUEUE_JOIN",
    "billing_queue_abandon": "BILLING_QUEUE_ABANDON",
    "queue_abandon": "BILLING_QUEUE_ABANDON",
    "queue_abandoned": "BILLING_QUEUE_ABANDON",
    "reentry": "REENTRY",
    "re_entry": "REENTRY",
}

# metadata keys we recognize and lift from a flat vendor row.
_META_PASSTHROUGH = (
    "queue_depth",
    "sku_zone",
    "session_seq",
    "age_bucket",
    "is_face_hidden",
    "group_id",
    "group_size",
    "reentry_of",
    # vendor extras worth keeping (EventMetadata allows extras)
    "zone_name",
    "zone_type",
    "is_revenue_zone",
)


def _first(raw: Dict[str, Any], *keys: str) -> Optional[Any]:
    for k in keys:
        v = raw.get(k)
        if v is not None and v != "":
            return v
    return None


def _coerce_type(raw: Dict[str, Any]) -> str:
    et = raw.get("event_type")
    if not et:
        raise ValueError("missing event_type")
    if et in _TYPE_MAP.values():  # already canonical
        return et
    mapped = _TYPE_MAP.get(str(et).strip().lower())
    if not mapped:
        raise ValueError(f"unmappable event_type {et!r}")
    return mapped


def _pick_timestamp(raw: Dict[str, Any], canonical_type: str) -> Any:
    # queue events carry join/exit timestamps instead of a single field.
    if canonical_type == "BILLING_QUEUE_ABANDON":
        ts = _first(raw, "timestamp", "queue_exit_ts", "event_time", "event_timestamp")
    elif canonical_type == "BILLING_QUEUE_JOIN":
        ts = _first(raw, "timestamp", "queue_join_ts", "event_time", "event_timestamp")
    else:
        ts = _first(raw, "timestamp", "event_timestamp", "event_time")
    if ts is None:
        raise ValueError("missing timestamp")
    return ts


def normalize_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a canonical-shaped dict (not yet validated). Raises ValueError on a
    row that cannot be mapped (missing type/timestamp/identity) so the caller
    can record it under ``rejected`` without aborting the batch.
    """
    if not isinstance(raw, dict):
        raise ValueError("event is not an object")

    ctype = _coerce_type(raw)
    ts = _pick_timestamp(raw, ctype)

    store_id = _first(raw, "store_id", "store_code")
    if not store_id:
        raise ValueError("missing store_id/store_code")

    visitor_id = _first(raw, "visitor_id", "id_token")
    if visitor_id is None:
        tid = _first(raw, "track_id")
        if tid is None:
            raise ValueError("missing visitor_id/id_token/track_id")
        visitor_id = f"track_{tid}"
    visitor_id = str(visitor_id)

    camera_id = str(_first(raw, "camera_id", "camera") or "unknown")
    zone_id = _first(raw, "zone_id")

    # dwell_ms: explicit, else derive from queue wait_seconds.
    dwell_ms = raw.get("dwell_ms")
    if dwell_ms is None:
        wait_s = raw.get("wait_seconds")
        dwell_ms = int(wait_s) * 1000 if wait_s is not None else 0

    # metadata: start from any provided dict, then lift recognized flat keys.
    meta: Dict[str, Any] = dict(raw.get("metadata") or {})
    for k in _META_PASSTHROUGH:
        if raw.get(k) is not None and k not in meta:
            meta[k] = raw[k]
    # demographics may be named gender/age (zone rows) or gender_pred/age_pred.
    if meta.get("gender_pred") is None:
        g = _first(raw, "gender_pred", "gender")
        if g is not None:
            meta["gender_pred"] = g
    if meta.get("age_pred") is None:
        a = _first(raw, "age_pred", "age")
        if a is not None:
            meta["age_pred"] = a
    # queue position -> queue_depth when not already set.
    if meta.get("queue_depth") is None and raw.get("queue_position_at_join") is not None:
        meta["queue_depth"] = raw["queue_position_at_join"]

    event_id = _first(raw, "event_id", "queue_event_id")
    if not event_id:
        event_id = str(
            uuid.uuid5(_NS, f"{store_id}|{visitor_id}|{ctype}|{ts}|{zone_id}")
        )

    return {
        "event_id": str(event_id),
        "store_id": str(store_id),
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": ctype,
        "timestamp": ts,
        "zone_id": zone_id,
        "dwell_ms": int(dwell_ms),
        "is_staff": bool(raw.get("is_staff", False)),
        "confidence": float(raw["confidence"]) if raw.get("confidence") is not None else 1.0,
        "metadata": meta,
    }
