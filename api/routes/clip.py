"""GET /clip/{camera} — stream a camera's CCTV clip (HTTP range supported).

Serves the secured source footage so the dashboard can play the segment around
a flagged incident. Allowlisted camera names only; 404 if the footage isn't
present (e.g. a fresh clone without the gitignored sample videos).

NOTE: raw footage — must be authenticated in production. No auth in this demo.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.clips import video_path

router = APIRouter()


@router.get("/clip/{camera}")
def get_clip(camera: str):
    path = video_path(camera)
    if path is None:
        raise HTTPException(status_code=404, detail="footage not available for this camera")
    # Starlette's FileResponse honours the Range header (206 partial content),
    # which is what lets the <video> element seek to the incident timestamp.
    return FileResponse(path, media_type="video/mp4", filename=f"{camera}.mp4")
