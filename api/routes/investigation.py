"""GET /investigation?since=&kinds= — loss-prevention review prompts.

Privacy-preserving: each incident is a behavioural review prompt with a camera +
timestamp + clip reference (NO identity / biometric data). A reviewer uses the
clip_ref to pull the secured source footage. Sorted by severity then time.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from services.event_store import store
from services.investigation import INCIDENT_DETECTORS, find_incidents
from services.pos_join import pos
from services.window import resolve_window

router = APIRouter()


@router.get("/investigation")
def get_investigation(
    since: Optional[str] = Query(None, description="Lower time bound (ISO-8601)"),
    kinds: Optional[str] = Query(None, description="Comma-separated incident kinds"),
):
    win_from, win_to = resolve_window(since, None)
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    incidents = find_incidents(store, pos, win_from, win_to, kind_list)
    return {
        "window": {"from": win_from, "to": win_to},
        "kinds_available": [d.kind for d in INCIDENT_DETECTORS],
        "count": len(incidents),
        "note": (
            "Behavioural review prompts only — a flag means 'a human should look', "
            "not that wrongdoing occurred. No identity/biometric data is stored; "
            "use clip_ref to review the secured source footage."
        ),
        "incidents": incidents,
    }
