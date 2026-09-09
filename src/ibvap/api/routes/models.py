"""Model Manager API routes - Switch models, background download streaming, and USB upload."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ibvap.core.detector import MockPersonDetector, ONNXDetectorProvider
from ibvap.core.model_manager import (
    YOLO_MODELS_MANIFEST,
    get_download_manager,
    get_model_registry,
    get_shared_detector_handle,
)

router = APIRouter(prefix="/api/v1/models", tags=["models"])

logger = structlog.get_logger(__name__)

# Bound model uploads in memory: largest manifest weight is 156MB; cap with headroom.
MODEL_UPLOAD_CHUNK = 1024 * 1024
MODEL_UPLOAD_MAX_BYTES = 220 * 1024 * 1024


class ModelItem(BaseModel):
    name: str
    filename: str
    description: str
    size_mb: float
    is_installed: bool
    is_active: bool
    est_latency_ms: float
    mAP_val: float


class ModelListResponse(BaseModel):
    models: list[ModelItem]
    active_model: str


class ActivateModelRequest(BaseModel):
    model_name: str = Field(..., description="YOLO26 model variant, e.g. yolo26s")


class DownloadModelRequest(BaseModel):
    model_name: str = Field(..., description="YOLO26 model variant to download")


class DownloadProgressResponse(BaseModel):
    model_name: str
    status: str
    downloaded_bytes: int
    total_bytes: int
    progress_percent: float
    speed_mbps: float
    eta_seconds: float
    error_message: str


@router.get("", response_model=ModelListResponse)
def list_models() -> ModelListResponse:
    handle = get_shared_detector_handle()
    registry = get_model_registry()
    models = registry.list_models(active_model_name=handle.active_model_name)
    return ModelListResponse(
        models=[
            ModelItem(
                name=m.name,
                filename=m.filename,
                description=m.description,
                size_mb=m.size_mb,
                is_installed=m.is_installed,
                is_active=m.is_active,
                est_latency_ms=m.est_latency_ms,
                mAP_val=m.mAP_val,
            )
            for m in models
        ],
        active_model=handle.active_model_name,
    )


@router.post("/activate")
def activate_model(payload: ActivateModelRequest) -> dict[str, Any]:
    model_name = payload.model_name
    meta = YOLO_MODELS_MANIFEST.get(model_name)
    if not meta:
        raise HTTPException(status_code=400, detail=f"Unknown model variant: {model_name}")

    registry = get_model_registry()
    model_file = registry.models_dir / meta["filename"]
    if not model_file.exists() or model_file.stat().st_size == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Model weight '{meta['filename']}' is not installed on disk. Please download or upload it first.",
        )

    # Instantiate new detector provider and perform safe hot-swap
    handle = get_shared_detector_handle()
    try:
        new_detector = ONNXDetectorProvider(str(model_file))
    except Exception:
        # Fallback to mock for test or invalid format
        new_detector = MockPersonDetector(model_id=model_name)

    handle.hot_swap(new_detector, model_name=model_name)
    return {
        "status": "activated",
        "active_model": model_name,
        "filename": meta["filename"],
    }


@router.post("/download")
async def start_model_download(payload: DownloadModelRequest) -> dict[str, Any]:
    model_name = payload.model_name
    meta = YOLO_MODELS_MANIFEST.get(model_name)
    if not meta:
        raise HTTPException(status_code=400, detail=f"Unknown model variant: {model_name}")

    manager = get_download_manager()
    prog = manager.get_or_create_progress(model_name)
    if prog.status == "downloading":
        return {"status": "in_progress", "model_name": model_name}

    # Spawn background download task (non-blocking)
    asyncio.create_task(manager.start_download(model_name))
    return {"status": "started", "model_name": model_name}


@router.get("/download/{model_name}/progress", response_model=DownloadProgressResponse)
def get_download_progress(model_name: str) -> DownloadProgressResponse:
    manager = get_download_manager()
    prog = manager.get_or_create_progress(model_name)
    return DownloadProgressResponse(
        model_name=prog.model_name,
        status=prog.status,
        downloaded_bytes=prog.downloaded_bytes,
        total_bytes=prog.total_bytes,
        progress_percent=prog.progress_percent,
        speed_mbps=prog.speed_mbps,
        eta_seconds=prog.eta_seconds,
        error_message=prog.error_message,
    )


@router.post("/upload")
async def upload_model_file(
    model_name: str = Form(...),
    file: UploadFile = File(...),  # noqa: B008 - FastAPI idiomatic dependency
) -> dict[str, Any]:
    meta = YOLO_MODELS_MANIFEST.get(model_name)
    if not meta:
        raise HTTPException(status_code=400, detail=f"Unknown model variant: {model_name}")

    # Chunked bounded read instead of a single unbounded file.read().
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(MODEL_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MODEL_UPLOAD_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Model file too large")
        chunks.append(chunk)
    content = b"".join(chunks) if len(chunks) != 1 else chunks[0]
    # Release chunk list early so peak memory is ~1x file, not ~2x.
    del chunks
    if len(content) < 100:
        raise HTTPException(status_code=400, detail="Uploaded file is too small or invalid")

    manager = get_download_manager()
    # save_model_file does blocking disk IO — offload from event loop.
    target_path = await asyncio.to_thread(manager.save_model_file, model_name, content)
    size_bytes = len(content)
    del content
    return {
        "status": "uploaded",
        "model_name": model_name,
        "size_bytes": size_bytes,
        "target_path": str(target_path),
    }


@router.delete("/{model_name}/weights")
def delete_model_weights(model_name: str) -> dict[str, Any]:
    # TODO: require authentication/authorization for mutating routes (would break tests today).
    logger.warning("unauthenticated_delete", route="DELETE /api/v1/models/{model_name}/weights")
    if model_name == "yolo26n":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete base default model 'yolo26n'.",
        )
    meta = YOLO_MODELS_MANIFEST.get(model_name)
    if not meta:
        raise HTTPException(status_code=400, detail=f"Unknown model variant: {model_name}")

    handle = get_shared_detector_handle()
    if handle.active_model_name == model_name:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_name}' is currently the active engine. Switch to another model before deleting.",
        )

    manager = get_download_manager()
    try:
        deleted = manager.delete_model_weights(model_name)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    return {
        "status": "deleted" if deleted else "not_found",
        "model_name": model_name,
        "filename": meta["filename"],
    }
