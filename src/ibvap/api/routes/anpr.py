"""ANPR Sightings API routes - historical vehicle license plate captures."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ibvap.core.anpr import get_sightings_store

router = APIRouter(prefix="/api/v1/anpr", tags=["anpr"])


class SightingItem(BaseModel):
    id: str
    camera_id: str
    plate_text: str
    confidence: float
    vehicle_class: str
    timestamp: float
    sight_count: int = 1
    bbox_norm: tuple[float, float, float, float] | None = None


@router.get("/sightings", response_model=list[SightingItem])
def get_sightings(
    plate: str | None = Query(None, description="Search by plate text or prefix"),
    camera_id: str | None = Query(None, description="Filter by camera ID"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    store = get_sightings_store()
    results = store.query_sightings(plate_prefix=plate, camera_id=camera_id, limit=limit)
    return [
        {
            "id": s.id,
            "camera_id": s.camera_id,
            "plate_text": s.plate_text,
            "confidence": s.confidence,
            "vehicle_class": s.vehicle_class,
            "timestamp": s.timestamp,
            "sight_count": s.sight_count,
            "bbox_norm": s.bbox_norm,
        }
        for s in results
    ]
