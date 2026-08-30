"""Health + capabilities - Phase 1 executable foundation."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ibvap.config import Settings
from ibvap.core.media_gateway import MediaGatewayClient

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


def _get_media_gateway_client(request: Request | None = None) -> MediaGatewayClient:
    api_url = "http://localhost:9997"
    if request is not None and hasattr(request.app.state, "settings") and request.app.state.settings is not None:
        api_url = request.app.state.settings.media.mediamtx_api_url
    else:
        with contextlib.suppress(Exception):
            api_url = Settings().media.mediamtx_api_url
    return MediaGatewayClient(api_url=api_url, timeout=1.0)


@router.get("/api/v1/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    client = _get_media_gateway_client(request)
    try:
        gateway_online = await client.check_health()
    finally:
        await client.close()

    media_gateway_status = "mediamtx-1.20.1-online" if gateway_online else "offline"

    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
        checks={
            "api": "ok",
            "database": "pending-postgres",
            "media": "pyav-18.1.0",
            "media_gateway": media_gateway_status,
        },
    )


@router.get("/api/v1/capabilities", response_model=CapabilitiesResponse)
async def capabilities(request: Request) -> CapabilitiesResponse:
    client = _get_media_gateway_client(request)
    try:
        gateway_online = await client.check_health()
    finally:
        await client.close()

    gateway_desc = "mediamtx 1.20.1 (online)" if gateway_online else "mediamtx 1.20.1 (replaceable)"

    return CapabilitiesResponse(
        version="0.1.0",
        python="3.12",
        database="postgresql+asyncpg 17/18 (async, outbox pending)",
        media={
            "gateway": gateway_desc,
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
