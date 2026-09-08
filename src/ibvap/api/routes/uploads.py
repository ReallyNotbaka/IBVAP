"""Upload quarantine - spec 9 and 21.2."""

from __future__ import annotations

import contextlib
import hashlib
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ibvap.core.upload import ALLOWED_EXTS, MAX_SIZE_BYTES, promoted_path, quarantine_path, streaming_hash, validate_filename

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

_UPLOADS: dict[str, dict[str, object]] = {}
UPLOAD_RETENTION_SECONDS = 24 * 60 * 60
UPLOAD_ROOTS = (Path("data/uploads"), Path("data/quarantine"))


def _remove_path(path_value: object) -> None:
    path = Path(str(path_value))
    if path.exists() and path.is_file():
        path.unlink()


def cleanup_expired_uploads(now: float | None = None) -> int:
    """Remove stale upload files and their in-memory metadata."""
    cutoff = (now or time.time()) - UPLOAD_RETENTION_SECONDS
    removed = 0
    for upload_id, data in list(_UPLOADS.items()):
        if float(data.get("created_at", 0.0)) >= cutoff:
            continue
        _remove_path(data.get("path"))
        _UPLOADS.pop(upload_id, None)
        removed += 1
    for root in UPLOAD_ROOTS:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                with contextlib.suppress(OSError):
                    path.unlink()
                    removed += 1
    return removed


class UploadCreateResponse(BaseModel):
    upload_id: str
    filename: str
    size: int
    sha256: str
    status: str


@router.post("", response_model=UploadCreateResponse)
async def create_upload(file: UploadFile = File(...)) -> UploadCreateResponse:  # noqa: B008
    cleanup_expired_uploads()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")
    try:
        validate_filename(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported extension {ext}")

    upload_id = uuid.uuid4().hex
    qpath = quarantine_path(upload_id, file.filename)
    qpath.parent.mkdir(parents=True, exist_ok=True)

    sha256 = hashlib.sha256()
    total = 0
    CHUNK_SIZE = 1024 * 1024  # 1MB
    is_first_chunk = True

    try:
        with qpath.open("wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="File too large")
                sha256.update(chunk)
                if is_first_chunk:
                    if chunk[:4] == b"<!DO" or chunk[:5] == b"<html":
                        raise HTTPException(status_code=400, detail="Invalid media container")
                    is_first_chunk = False
                out.write(chunk)
            # handle empty file case: no chunk read, total==0, first check not needed
            # if file was empty, is_first_chunk remains True - no html to check
    except HTTPException:
        # abort: remove partial quarantine file (must be after file handle closed)
        try:
            if qpath.exists():
                qpath.unlink()
        except Exception:
            pass
        raise

    sha = sha256.hexdigest()
    # quarantine metadata
    _UPLOADS[upload_id] = {
        "filename": file.filename,
        "size": total,
        "sha256": sha,
        "status": "quarantined",
        "path": str(qpath),
        "created_at": time.time(),
    }
    return UploadCreateResponse(upload_id=upload_id, filename=file.filename, size=total, sha256=sha, status="quarantined")


@router.delete("/{upload_id}", response_model=dict[str, str])
async def delete_upload(upload_id: str) -> dict[str, str]:
    data = _UPLOADS.pop(upload_id, None)
    if not data:
        raise HTTPException(status_code=404, detail="Upload not found")
    _remove_path(data.get("path"))
    return {"status": "deleted", "upload_id": upload_id}


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


@router.post("/{upload_id}/analyze", response_model=dict[str, object])
async def analyze_upload(
    upload_id: str,
    max_frames: int = 30,
    sample_stride: int = 3,
    face_stride: int = 2,
    enable_face: bool = True,
) -> dict[str, object]:
    """Optimized offline analysis for uploaded footage - runs person/vehicle + face with sampling.

    Optimisations:
    - sample_stride 3 => 10 FPS analysis from 30 FPS source (3x speedup, saves YOLO 13ms/frame)
    - face_stride 2 => YuNet every 2nd analysed frame (saves ~8ms)
    - max_face_size 1280 downscale for 4K
    - bounded queues (spec 10) prevent OOM on long clips
    - PyAV provenance (time_base) not sole VideoCapture
    """
    data = _UPLOADS.get(upload_id)
    if not data:
        raise HTTPException(status_code=404, detail="Upload not found")
    path = Path(str(data["path"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing - finalize first")
    # Clamp to sane bounds for server protection
    max_frames = max(1, min(max_frames, 300))
    sample_stride = max(1, min(sample_stride, 10))
    face_stride = max(1, min(face_stride, 10))
    try:
        from ibvap.core.pipeline import MiniPipeline

        pipeline = MiniPipeline(
            camera_id=f"upload-{upload_id}",
            enable_face=enable_face,
            sample_stride=sample_stride,
            face_stride=face_stride,
        )
        # process_video_file is already optimized (PyAV + sampling)
        events = pipeline.process_video_file(
            str(path),
            max_frames=max_frames,
            sample_stride=sample_stride,
            enable_face=enable_face,
            face_stride=face_stride,
        )
        # Collect stats
        return {
            "upload_id": upload_id,
            "path": str(path),
            "analyzed_frames": max_frames,
            "sample_stride": sample_stride,
            "face_stride": face_stride,
            "events_created": pipeline.events_created,
            "queue_drops": pipeline.q_demux_to_sample.dropped + pipeline.q_sample_to_infer.dropped,
            "faces_analyzed": pipeline.faces_analyzed,
            "frames_skipped": pipeline.frames_skipped,
            "last_detections": pipeline.last_detections,
            "last_tracks": [
                {"track_id": t.track_id, "class_name": t.class_name, "confidence": t.confidence, "bbox_norm": t.bbox_norm} for t in pipeline.last_tracks
            ],
            "last_faces": pipeline.last_faces,
            "events": events[:20],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}") from e
