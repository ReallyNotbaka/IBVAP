"""Watchlist API routes - Biometric enrollment, query, and un-enrollment."""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import Any

import cv2
import numpy as np
import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ibvap.core.face import FaceDetector, FaceRecognizer
from ibvap.core.watchlist import ThreatLevel, WatchlistEntry, get_watchlist_store

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])

logger = structlog.get_logger(__name__)

# Bound per-photo in-memory reads (photos are small; models/uploads handle large files).
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_DIM = 1920

_detector: FaceDetector | None = None
_recognizer: FaceRecognizer | None = None


def _get_face_models() -> tuple[FaceDetector, FaceRecognizer]:
    global _detector, _recognizer
    if _detector is None:
        _detector = FaceDetector()
    if _recognizer is None:
        _recognizer = FaceRecognizer()
    return _detector, _recognizer


class WatchlistSummaryItem(BaseModel):
    id: str
    name: str
    threat_level: str
    notes: str
    created_at: float
    photo_count: int
    thumbnail_b64: str
    sight_count: int
    last_sighted: float | None


class WatchlistResponse(BaseModel):
    entries: list[WatchlistSummaryItem]


@router.get("", response_model=WatchlistResponse)
def list_watchlist() -> WatchlistResponse:
    store = get_watchlist_store()
    items = []
    for e in store.list_entries():
        items.append(
            WatchlistSummaryItem(
                id=e.id,
                name=e.name,
                threat_level=e.threat_level.value,
                notes=e.notes,
                created_at=e.created_at,
                photo_count=len(e.gallery),
                thumbnail_b64=e.thumbnail_b64,
                sight_count=e.sight_count,
                last_sighted=e.last_sighted,
            )
        )
    return WatchlistResponse(entries=items)


@router.post("/enroll")
async def enroll_suspect(
    name: str = Form(...),
    threat_level: str = Form("HIGH"),
    notes: str = Form(""),
    photos: list[UploadFile] = File(...),  # noqa: B008 - FastAPI idiomatic dependency
) -> dict[str, Any]:
    if not photos:
        raise HTTPException(status_code=400, detail="At least one photo is required for biometric enrollment")
    if len(photos) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 photos allowed per suspect")

    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    try:
        level = ThreatLevel(threat_level.upper())
    except ValueError:
        # Backward compat: invalid levels fall back to HIGH (do NOT 400 to avoid breaking clients).
        logger.warning("invalid_threat_level_fallback", threat_level=threat_level)
        level = ThreatLevel.HIGH

    detector, recognizer = _get_face_models()
    gallery: list[np.ndarray] = []
    thumbnail_b64 = ""
    rejection_reasons: list[str] = []

    for idx, photo in enumerate(photos):
        # Bounded read: fail fast on oversize instead of unbounded buffering.
        content = await photo.read(MAX_PHOTO_BYTES + 1)
        if len(content) > MAX_PHOTO_BYTES:
            rejection_reasons.append(f"Photo {idx + 1}: file too large (max 10MB)")
            continue
        if not content:
            rejection_reasons.append(f"Photo {idx + 1}: unreadable image file")
            continue

        def _decode_and_detect(payload: bytes) -> tuple[Any, list[Any]]:
            arr = np.frombuffer(payload, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                return None, []
            # Downscale oversized enrollment photos to bound CPU/memory.
            h0, w0 = img.shape[:2]
            scale = min(1.0, MAX_PHOTO_DIM / max(h0, w0))
            if scale < 1.0:
                img = cv2.resize(img, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_LINEAR)
            return img, detector.detect(img)

        img, faces = await asyncio.to_thread(_decode_and_detect, bytes(content))
        if img is None or img.size == 0:
            rejection_reasons.append(f"Photo {idx + 1}: unreadable image file")
            continue

        h, w = img.shape[:2]
        faces = detector.detect(img)
        if not faces:
            rejection_reasons.append(f"Photo {idx + 1}: no face detected")
            continue

        # Find largest face by area
        best_face = max(faces, key=lambda f: (f.bbox_norm[2] - f.bbox_norm[0]) * (f.bbox_norm[3] - f.bbox_norm[1]))
        bx1, by1, bx2, by2 = best_face.bbox_norm
        fw = (bx2 - bx1) * w
        fh = (by2 - by1) * h

        # Quality Gating
        if fw < 40 or fh < 40:
            rejection_reasons.append(f"Photo {idx + 1}: face too small ({int(fw)}x{int(fh)} < 40x40)")
            continue

        if abs(best_face.quality.pose_yaw) > 40.0:
            rejection_reasons.append(f"Photo {idx + 1}: head turned too far ({best_face.quality.pose_yaw:.1f} deg)")
            continue

        if best_face.quality.blur < 15.0:
            rejection_reasons.append(f"Photo {idx + 1}: image too blurry (blur {best_face.quality.blur:.1f} < 15.0)")
            continue

        # Extract 128-d embedding (blocking CPU — offload from event loop).
        def _embed(image: Any, face: Any) -> Any:
            aligned = recognizer.align_crop(image, face)
            feat = recognizer.extract_feature(aligned).flatten()
            return aligned, feat

        aligned, feat = await asyncio.to_thread(_embed, img, best_face)
        feat_norm = np.linalg.norm(feat)
        if feat_norm > 0:
            feat = feat / feat_norm
            gallery.append(feat)

            # Generate thumbnail from first valid aligned crop
            if not thumbnail_b64:
                thumb = cv2.resize(aligned, (96, 96))
                ok, encoded = cv2.imencode(".jpg", thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    thumbnail_b64 = base64.b64encode(encoded.tobytes()).decode("ascii")

    if not gallery:
        msg = "No suitable faces found for enrollment. " + "; ".join(rejection_reasons)
        raise HTTPException(status_code=400, detail=msg)

    suspect_id = f"suspect-{uuid.uuid4().hex[:8]}"
    entry = WatchlistEntry(
        id=suspect_id,
        name=name,
        threat_level=level,
        notes=notes,
        created_at=time.time(),
        gallery=gallery,
        thumbnail_b64=thumbnail_b64,
    )
    get_watchlist_store().add_entry(entry)

    return {
        "status": "enrolled",
        "entry": {
            "id": entry.id,
            "name": entry.name,
            "threat_level": entry.threat_level.value,
            "notes": entry.notes,
            "photo_count": len(entry.gallery),
            "thumbnail_b64": entry.thumbnail_b64,
        },
    }


@router.delete("/{entry_id}")
def delete_suspect(entry_id: str) -> dict[str, Any]:
    # TODO: require authentication/authorization for mutating routes (would break tests today).
    logger.warning("unauthenticated_delete", route="DELETE /api/v1/watchlist/{entry_id}")
    store = get_watchlist_store()
    removed = store.remove_entry(entry_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Suspect with ID '{entry_id}' not found")
    return {"status": "removed", "id": entry_id}
