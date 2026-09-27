"""Evidence API routes for retrieving forensic snapshots and target crops."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ibvap.core.evidence import get_evidence_file, validate_event_id

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


def _checked_event_id(event_id: str) -> str:
    # Task 1 P0: traversal guard — 422 on bad id (not 404-from-missing-file).
    try:
        return validate_event_id(event_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid event_id") from None


@router.get("/{event_id}/snapshot")
async def get_evidence_snapshot(event_id: str) -> FileResponse:
    """Retrieve full-frame forensic JPEG snapshot for an event."""
    event_id = _checked_event_id(event_id)
    path = get_evidence_file(event_id, kind="snapshot")
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence snapshot not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{event_id}/crop")
async def get_evidence_crop(event_id: str) -> FileResponse:
    """Retrieve target-cropped JPEG evidence for an event."""
    event_id = _checked_event_id(event_id)
    path = get_evidence_file(event_id, kind="crop")
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence crop not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
