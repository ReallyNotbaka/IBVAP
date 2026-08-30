"""Health + capabilities - Phase 1 executable foundation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    checks: dict[str, str]


class CapabilitiesResponse(BaseModel):
    version: str
    python: str
    database: str
    media: dict[str, str]
    detectors: dict[str, Any]
    features: dict[str, bool]


@router.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
        checks={"api": "ok", "database": "pending-postgres", "media": "pyav-18.1.0"},
    )


@router.get("/api/v1/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        version="0.1.0",
        python="3.12",
        database="postgresql+asyncpg 17/18 (async, outbox pending)",
        media={
            "gateway": "mediamtx 1.20.1 (replaceable)",
            "decoder": "PyAV 18.1.0 (FFmpeg 8.x)",
            "opencv": "5.0.0.93",
        },
        detectors={
            "primary": "YOLO26 BLOCKED until Enterprise grant or RF-DETR ratified (see docs/adr/0004)",
            "fallback": "RF-DETR (Apache-2.0) documented as alternative",
            "face": "YuNet/SFace (pending legal, disabled-by-default identity)",
            "plate": "PaddleOCR 3.7.0 PP-OCRv6 + dedicated plate detector (pending artifact)",
        },
        features={
            "smartphone_ip_webcam": True,
            "rtsp_rtsps": True,
            "mjpeg_adapter": True,
            "whip_whep": True,
            "hls_fallback": True,
            "postgres_outbox": False,  # pending migration + relay
            "s3_evidence": False,
        },
    )


@router.get("/api/v1/system/version")
async def system_version() -> dict[str, str]:
    return {"version": "0.1.0", "python": "3.12", "uv": "0.12.3"}
