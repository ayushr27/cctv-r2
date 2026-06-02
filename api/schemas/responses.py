"""Pydantic response models for the API endpoints (plan §6)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class MetricsResponse(BaseModel):
    window: dict
    footfall: int
    unique_groups: int
    staff_count: int = 0
    peak_hour: Optional[str]
    avg_dwell_seconds: float
    conversion_rate: Optional[float] = None
    avg_bill_value: Optional[float] = None
    total_revenue: Optional[float] = None


class EventEnvelope(BaseModel):
    event_id: str
    ts: str
    type: str
    camera: Optional[str] = None
    payload: dict


class EventsResponse(BaseModel):
    window: dict
    count: int
    limit: int
    events: List[EventEnvelope]
