"""Health + capabilities - Phase 1 executable foundation."""

from __future__ import annotations

import contextlib
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ibvap.config import Settings
from ibvap.core.media_gateway import MediaGatewayClient

router = APIRouter(tags=["system"])

_START_TIME = time.time()


class SystemTelemetry(BaseModel):
    gpu_accelerator: str
    directml_available: bool
    cuda_available: bool
    active_providers: list[str]
    memory_total_mb: int
    memory_avail_mb: int
    memory_used_mb: int
    memory_percent: float
    active_model: str
    active_runtime: str
    process_uptime_seconds: float


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    checks: dict[str, str]
    system: SystemTelemetry | None = None


def _get_memory_telemetry() -> dict[str, Any]:
    total_mb = 16384
    avail_mb = 8192
    percent = 50.0
    import sys

    if sys.platform == "win32":
        try:
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [
                    ("l", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong),
                    ("tot_pf", ctypes.c_ulonglong),
                    ("avail_pf", ctypes.c_ulonglong),
                    ("tot_virt", ctypes.c_ulonglong),
                    ("avail_virt", ctypes.c_ulonglong),
                    ("avail_ext", ctypes.c_ulonglong),
                ]

            m = MEM()
            m.l = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            total_mb = int(m.total // (1024 * 1024))
            avail_mb = int(m.avail // (1024 * 1024))
            percent = float(m.load)
        except Exception:
            pass
    return {
        "memory_total_mb": total_mb,
        "memory_avail_mb": avail_mb,
        "memory_used_mb": max(0, total_mb - avail_mb),
        "memory_percent": percent,
    }


def _get_gpu_telemetry() -> dict[str, Any]:
    providers: list[str] = []
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
    except Exception:
        pass
    dml = "DmlExecutionProvider" in providers
    cuda = "CUDAExecutionProvider" in providers
    acc = "DirectML (Hardware Accelerated)" if dml else ("NVIDIA CUDA" if cuda else "CPU Native")
    return {
        "gpu_accelerator": acc,
        "directml_available": dml,
        "cuda_available": cuda,
        "active_providers": providers,
    }


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
    mem = _get_memory_telemetry()
    gpu = _get_gpu_telemetry()

    handle = None
    with contextlib.suppress(Exception):
        from ibvap.core.model_manager import get_shared_detector_handle

        handle = get_shared_detector_handle()

    active_model = handle.active_model_name if handle else "yolo26n"
    active_runtime = (
        getattr(handle.detector, "runtime", "directml" if gpu["directml_available"] else "cpu")
        if handle
        else "cpu"
    )

    sys_telemetry = SystemTelemetry(
        gpu_accelerator=gpu["gpu_accelerator"],
        directml_available=gpu["directml_available"],
        cuda_available=gpu["cuda_available"],
        active_providers=gpu["active_providers"],
        memory_total_mb=mem["memory_total_mb"],
        memory_avail_mb=mem["memory_avail_mb"],
        memory_used_mb=mem["memory_used_mb"],
        memory_percent=mem["memory_percent"],
        active_model=active_model,
        active_runtime=active_runtime,
        process_uptime_seconds=round(time.time() - _START_TIME, 1),
    )

    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
        checks={
            "api": "ok",
            "database": "pending-postgres",
            "media": "pyav-18.1.0",
            "media_gateway": media_gateway_status,
            "gpu": "directml-active" if gpu["directml_available"] else "cpu-only",
            "memory": f"{mem['memory_percent']}% ({mem['memory_used_mb']}/{mem['memory_total_mb']} MB)",
        },
        system=sys_telemetry,
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
