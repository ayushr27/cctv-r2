"""
Pydantic v2 event models — the single source of truth for the event schema.

Imported by both the worker (worker/events.py, worker/classify.py) and the API
(copied/imported as api/schemas/events.py). Every event shares a common envelope
(event_id, ts, type, payload) and carries a strictly-typed payload. The top-level
``Event`` is a discriminated union keyed on ``type`` so a JSONL line parses into
exactly the right model.

Event types (plan §5):
  worker-emitted:
    visit.entered, visit.entered_zone, visit.exited_zone,
    visit.approached_cash, visit.ended, track.staff_classified
  api-emitted (derived):
    pos.bill_created, anomaly.detected
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Iterable, List, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter

# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class VisitEnteredPayload(BaseModel):
    visit_id: str
    track_id: int
    entry_line: str
    group_id: Optional[str] = None
    group_size: int = 1


class VisitEnteredZonePayload(BaseModel):
    visit_id: str
    track_id: int
    zone: str


class VisitExitedZonePayload(BaseModel):
    visit_id: str
    track_id: int
    zone: str
    dwell_ms: int


class VisitApproachedCashPayload(BaseModel):
    visit_id: str
    track_id: int


VisitEndReason = Literal["track_lost", "crossed_exit_line", "end_of_footage"]


class VisitEndedPayload(BaseModel):
    visit_id: str
    track_id: int
    total_dwell_ms: int
    zones_visited: List[str] = Field(default_factory=list)
    reason: VisitEndReason


class StaffEvidence(BaseModel):
    total_dwell_ms: int
    zones_count: int
    cash_passes: int


class TrackStaffClassifiedPayload(BaseModel):
    visit_id: str
    track_id: int
    evidence: StaffEvidence


class PosBillCreatedPayload(BaseModel):
    invoice_number: str
    amount: float
    items: int
    salesperson_id: Optional[str] = None
    ts_source: Literal["csv"] = "csv"


AnomalySeverity = Literal["info", "warning", "critical"]


class AnomalyWindow(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime

    model_config = {"populate_by_name": True}


class AnomalyDetectedPayload(BaseModel):
    kind: str
    severity: AnomalySeverity
    window: AnomalyWindow
    observed: float
    expected_p50: Optional[float] = None
    z_score: Optional[float] = None
    evidence: str


# ---------------------------------------------------------------------------
# Envelope variants (discriminated on ``type``)
# ---------------------------------------------------------------------------


class _Envelope(BaseModel):
    event_id: str
    ts: datetime
    # Which camera produced this event (multi-camera deployment). Optional so
    # POS/anomaly and single-camera events remain valid without it.
    camera: Optional[str] = None


class VisitEntered(_Envelope):
    type: Literal["visit.entered"] = "visit.entered"
    payload: VisitEnteredPayload


class VisitEnteredZone(_Envelope):
    type: Literal["visit.entered_zone"] = "visit.entered_zone"
    payload: VisitEnteredZonePayload


class VisitExitedZone(_Envelope):
    type: Literal["visit.exited_zone"] = "visit.exited_zone"
    payload: VisitExitedZonePayload


class VisitApproachedCash(_Envelope):
    type: Literal["visit.approached_cash"] = "visit.approached_cash"
    payload: VisitApproachedCashPayload


class VisitEnded(_Envelope):
    type: Literal["visit.ended"] = "visit.ended"
    payload: VisitEndedPayload


class TrackStaffClassified(_Envelope):
    type: Literal["track.staff_classified"] = "track.staff_classified"
    payload: TrackStaffClassifiedPayload


class PosBillCreated(_Envelope):
    type: Literal["pos.bill_created"] = "pos.bill_created"
    payload: PosBillCreatedPayload


class AnomalyDetected(_Envelope):
    type: Literal["anomaly.detected"] = "anomaly.detected"
    payload: AnomalyDetectedPayload


Event = Annotated[
    Union[
        VisitEntered,
        VisitEnteredZone,
        VisitExitedZone,
        VisitApproachedCash,
        VisitEnded,
        TrackStaffClassified,
        PosBillCreated,
        AnomalyDetected,
    ],
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter = TypeAdapter(Event)


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def event_to_dict(event) -> dict:
    """Serialize a single event to a plain dict (ISO timestamps, ``from`` alias)."""
    return event.model_dump(mode="json", by_alias=True)


def dump_jsonl(events: Iterable, path) -> int:
    """Write events to a JSONL file atomically. Returns the count written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with open(tmp, "w") as f:
        for ev in events:
            f.write(json.dumps(event_to_dict(ev)) + "\n")
            count += 1
    tmp.rename(path)
    return count


def load_jsonl(path) -> List:
    """Parse a JSONL file into a list of validated Event models."""
    path = Path(path)
    out: List = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(EVENT_ADAPTER.validate_python(json.loads(line)))
    return out
