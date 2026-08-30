"""Upload quarantine - spec 9 and 21.2."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ibvap.core.upload import ALLOWED_EXTS, MAX_SIZE_BYTES, promoted_path, quarantine_path, streaming_hash

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

_UPLOADS: dict[str, dict[str, object]] = {}


class UploadCreateResponse(BaseModel):
    upload_id: str
    filename: str
    size: int
    sha256: str
    status: str


@router.post("", response_model=UploadCreateResponse)
async def create_upload(file: UploadFile = File(...)) -> UploadCreateResponse:  # noqa: B008
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported extension {ext}")
    content = await file.read()
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    # basic magic check - ensure not HTML pretending to be video
    if content[:4] == b"<!DO" or content[:5] == b"<html":
        raise HTTPException(status_code=400, detail="Invalid media container")
    upload_id = uuid.uuid4().hex
    qpath = quarantine_path(upload_id, file.filename)
    qpath.parent.mkdir(parents=True, exist_ok=True)
    qpath.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    # quarantine metadata
    _UPLOADS[upload_id] = {
        "filename": file.filename,
        "size": len(content),
        "sha256": sha,
        "status": "quarantined",
        "path": str(qpath),
    }
    return UploadCreateResponse(upload_id=upload_id, filename=file.filename, size=len(content), sha256=sha, status="quarantined")


@router.get("/{upload_id}", response_model=dict[str, object])
async def get_upload(upload_id: str) -> dict[str, object]:
    data = _UPLOADS.get(upload_id)
    if not data:
        raise HTTPException(status_code=404, detail="Upload not found")
    return data


@router.post("/{upload_id}/finalize", response_model=dict[str, object])
async def finalize_upload(upload_id: str) -> dict[str, object]:
    data = _UPLOADS.get(upload_id)
    if not data:
        raise HTTPException(status_code=404, detail="Upload not found")
    # re-hash and validate
    qpath = Path(str(data["path"]))
    if not qpath.exists():
        raise HTTPException(status_code=404, detail="Quarantined file missing")
    # sandboxed probe would run here via PyAV - for Phase 2 we just check hash
    sha = streaming_hash(qpath)
    if sha != data["sha256"]:
        raise HTTPException(status_code=400, detail="Hash mismatch")
    # promote
    ppath = promoted_path(upload_id, str(data["filename"]))
    ppath.parent.mkdir(parents=True, exist_ok=True)
    qpath.rename(ppath)
    data["status"] = "promoted"
    data["path"] = str(ppath)
    return data
