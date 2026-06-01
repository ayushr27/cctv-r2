"""GET /events?type=&from=&to=&limit= — paginated raw event feed.

Default limit 100, max 1000 (plan §6). Returns events in time order with the
echoed query window so the response is self-describing.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from schemas.responses import EventsResponse
from services.event_store import store

router = APIRouter()


@router.get("/events", response_model=EventsResponse)
def get_events(
    type: Optional[str] = Query(None, description="Filter by event type"),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    events = store.get_events(from_=from_, to_=to, type_=type, limit=limit)
    return EventsResponse(
        window={"from": from_, "to": to},
        count=len(events),
        limit=limit,
        events=events,
    )
