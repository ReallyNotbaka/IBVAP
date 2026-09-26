"""Evidence API routes for retrieving forensic snapshots and target crops."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ibvap.core.evidence import get_evidence_file

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get("/{event_id}/snapshot")
async def get_evidence_snapshot(event_id: str) -> FileResponse:
    """Retrieve full-frame forensic JPEG snapshot for an event."""
    path = get_evidence_file(event_id, kind="snapshot")
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence snapshot not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{event_id}/crop")
async def get_evidence_crop(event_id: str) -> FileResponse:
    """Retrieve target-cropped JPEG evidence for an event."""
    path = get_evidence_file(event_id, kind="crop")
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence crop not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
