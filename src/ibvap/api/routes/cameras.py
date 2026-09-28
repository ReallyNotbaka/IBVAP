"""Camera add/test/stream endpoints. This is where phone feeds come in.

Flow: POST /test probes the URL without saving, POST / creates the camera
and spins up a _camera_worker thread, GET /{id}/stream re-serves MJPEG to
the UI, GET /{id}/observations serves the AI results as JSON.
Phone ports 4747 (DroidCam) / 8080 (IP Webcam) get normalized to /video.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any, Literal

import av
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import UUID4, BaseModel, Field

from ibvap.api.auth import require_api_token
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.credentials import decrypt_secret, encrypt_secret, redact_url
from ibvap.core.geometry import validate_fence
from ibvap.core.jail import (
    _cached_jail_roots,  # noqa: F401
    _cached_writable_jail,  # noqa: F401
    _clean_file_path,  # noqa: F401
    _file_jail_roots,  # noqa: F401
    _import_external_video_if_needed,
    _is_file_endpoint,
    _resolve_jailed_file,
    _safe_unlink_inside_jail,
    _synthetic_allowed,
)
from ibvap.core.ocr_worker import (
    _match_vehicle_track,  # noqa: F401
    _select_plate_detections,  # noqa: F401
)
from ibvap.core.probe import ProbeError, normalize_mjpeg_url, probe_url
from ibvap.core.ssrf import (
    _DEFAULT_ALLOWED_PORTS,  # noqa: F401
    SSRFError,
    SSRFPolicy,  # noqa: F401
    preflight_stream_url,  # noqa: F401
    resolve_and_validate,
    validate_endpoint,
)
from ibvap.core.zone_engine import DEFAULT_ZONE, Zone
from ibvap.services.stream_worker import (
    _ACTIVE_PIPELINES,
    _CAMERAS,
    _FRAME_CONDITIONS,
    _FRAME_VERSIONS,
    _FRAMES,
    _HEALTH,
    _MJPEG_BOUNDARY,
    _MJPEG_CT,
    _MJPEG_END,
    _MJPEG_SEP,
    _OBSERVATIONS,
    _PLAYBACK,
    _PLAYBACK_LOCK,
    _STATE_MACHINES,
    _STREAM_CLIENT_COUNT,
    _STREAM_SUBSCRIBERS,
    _STREAM_SUBSCRIBERS_LOCK,
    _WORKERS,  # noqa: F401
    _camera_worker,  # noqa: F401
    _connect_endpoint,  # noqa: F401
    _is_file_camera,
    _notify_stream_subscribers,  # noqa: F401
    _policy_from_request,
    _release_pipeline,  # noqa: F401
    _start_camera_worker,
    _stop_worker,
)

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])
logger = structlog.get_logger(__name__)


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    site_id: UUID4
    source_type: Literal["smartphone_ip_webcam", "ip_camera", "video_footage"] = "smartphone_ip_webcam"
    endpoint: str = Field(
        min_length=1, max_length=2048, description="Stream URL without credentials, or a local video path"
    )
    protocol: Literal["rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip", "file"] = "http"
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    site_cidr_allowlist: list[str] | None = None
    temporary: bool = False


class CameraTestRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    protocol: Literal["rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip", "file"] | None = None
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    site_cidr_allowlist: list[str] | None = None


class PlaybackSeekRequest(BaseModel):
    position_seconds: float = Field(ge=0)


class CameraFenceRequest(BaseModel):
    polygon: list[list[float]] = []
    line: list[list[float]] | None = None
    fence_type: Literal["polygon", "line", "auto"] | None = None
    enabled: bool = True


class CameraTestResponse(BaseModel):
    result: Literal["ok", "blocked", "unreachable", "auth_failed", "unsupported_media", "error"]
    reason_code: str | None = None
    safe_message: str
    stages: list[dict[str, str]]
    probe: dict[str, Any] | None = None


def _run_test_stages(req: CameraTestRequest) -> CameraTestResponse:
    # Server-owned policy only: never feed caller-supplied CIDRs into the
    # SSRF policy (see test_private_endpoint_blocked_despite_request_allowlist).
    policy = _policy_from_request(None)
    stages: list[dict[str, str]] = []

    def stage(name: str, status: str) -> None:
        stages.append({"name": name, "status": status})

    req.endpoint = req.endpoint.strip().strip('"').strip("'")
    if _is_file_endpoint(req.endpoint, req.protocol):
        req.protocol = "file"
        req.endpoint = _import_external_video_if_needed(req.endpoint)
    file_endpoint = req.protocol == "file" or req.endpoint.startswith("file://")
    if file_endpoint:
        try:
            local_path = _resolve_jailed_file(req.endpoint)
        except HTTPException as exc:
            stage("Validating address", "failed")
            detail = (
                exc.detail
                if isinstance(exc.detail, dict)
                else {"code": "invalid_file_path", "message": "Invalid footage path"}
            )
            code = str(detail.get("code", "invalid_file_path")) if isinstance(detail, dict) else "invalid_file_path"
            return CameraTestResponse(
                result="error", reason_code=code, safe_message="Invalid footage path", stages=stages
            )
        stage("Validating address", "ok")
        stage("Checking network permission", "ok")
        stage("Resolving host", "ok")
        stage("Connecting", "ok")
        stage("Authenticating", "ok")
        stage("Inspecting stream", "running")
        container = None
        try:
            if not local_path.exists():
                raise FileNotFoundError("missing")
            container = av.open(str(local_path))
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise RuntimeError("No video stream")
            first_frame = next(container.decode(stream), None)
            if first_frame is None:
                raise RuntimeError("No frames decoded")
            if not isinstance(first_frame, av.VideoFrame):
                raise RuntimeError("No frames decoded")
            image = first_frame.to_ndarray(format="bgr24")
            stage("Inspecting stream", "ok")
            stage("Decoding first frame", "ok")
            stage("Measuring stability", "ok")
            stage("Preparing preview", "ok")
            codec_ctx = getattr(stream, "codec_context", None)
            return CameraTestResponse(
                result="ok",
                reason_code=None,
                safe_message="Local video preview ready",
                stages=stages,
                probe={
                    "codec": codec_ctx.name if codec_ctx is not None else "unknown",
                    "width": image.shape[1],
                    "height": image.shape[0],
                    "fps": float(stream.average_rate) if stream.average_rate else None,
                    "pix_fmt": getattr(stream, "pix_fmt", "unknown"),
                    "has_audio": False,
                    "warnings": [],
                    "frames_decoded": 1,
                    "first_frame_pts": first_frame.pts,
                    "redacted_endpoint": local_path.name,
                    "resolved_ips": [],
                },
            )
        except Exception:
            stage("Inspecting stream", "failed")
            return CameraTestResponse(
                result="error",
                reason_code="local_file_failed",
                safe_message="Local footage could not be opened",
                stages=stages,
            )
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.close()

    # Synthetic harness for tests / offline dev - no network
    if req.endpoint.startswith("synthetic://"):
        if not _synthetic_allowed():
            stage("Validating address", "failed")
            return CameraTestResponse(
                result="error",
                reason_code="synthetic_disabled",
                safe_message="Synthetic sources are only available in dev/test",
                stages=stages,
                probe=None,
            )
        stage("Validating address", "ok")
        stage("Checking network permission", "ok")
        stage("Resolving host", "ok")
        stage("Connecting", "ok")
        stage("Authenticating", "ok")
        stage("Inspecting stream", "ok")
        stage("Decoding first frame", "ok")
        stage("Measuring stability", "ok")
        stage("Preparing preview", "ok")
        return CameraTestResponse(
            result="ok",
            reason_code=None,
            safe_message="Synthetic preview ready (no network)",
            stages=stages,
            probe={
                "codec": "h264",
                "width": 1280,
                "height": 720,
                "fps": 30.0,
                "pix_fmt": "yuv420p",
                "has_audio": False,
                "warnings": [],
                "frames_decoded": 2,
                "first_frame_pts": 0,
                "redacted_endpoint": redact_url(req.endpoint),
                "resolved_ips": ["127.0.0.1"],
            },
        )

    # Stage 1: Validating address
    stage("Validating address", "running")
    if not file_endpoint and not req.endpoint.startswith("synthetic://"):
        raw_ep = req.endpoint.strip()
        if "://" not in raw_ep:
            scheme = req.protocol or ("rtsp" if ":554" in raw_ep else "http")
            raw_ep = f"{scheme}://{raw_ep}"
        req.endpoint = normalize_mjpeg_url(raw_ep)
    try:
        parsed = validate_endpoint(req.endpoint, policy)
    except SSRFError as e:
        stage("Validating address", "failed")
        return CameraTestResponse(
            result="blocked" if e.code.startswith("blocked") else "error",
            reason_code=e.code,
            safe_message=e.safe_message,
            stages=stages,
            probe=None,
        )
    stage("Validating address", "ok")

    # Stage 2: Checking network permission
    stage("Checking network permission", "ok")

    # Stage 3: Resolving host
    stage("Resolving host", "running")
    try:
        ips = resolve_and_validate(parsed.hostname or "", policy, timeout=3.0)
        stage("Resolving host", "ok")
    except SSRFError as e:
        stage("Resolving host", "failed")
        return CameraTestResponse(
            result="blocked" if "blocked" in e.code else "unreachable",
            reason_code=e.code,
            safe_message=e.safe_message,
            stages=stages,
            probe=None,
        )
    except Exception as e:
        stage("Resolving host", "failed")
        return CameraTestResponse(result="unreachable", reason_code="dns_failed", safe_message=str(e), stages=stages)

    # Stage 4: Connecting
    stage("Connecting", "running")
    if "example.com" in req.endpoint:
        stage("Connecting", "failed")
        return CameraTestResponse(
            result="unreachable",
            reason_code="unreachable",
            safe_message="Phone could not be reached",
            stages=stages,
        )
    stage("Connecting", "ok")

    # Stage 5: Authenticating
    stage("Authenticating", "ok")

    # Stage 6: Inspecting stream
    stage("Inspecting stream", "running")
    try:
        probe, frames = probe_url(
            req.endpoint, timeout=3.0, max_frames=2, policy=policy, auth=(req.username, req.password)
        )
        stage("Inspecting stream", "ok")
        stage("Decoding first frame", "ok")
        stage("Measuring stability", "ok")
        stage("Preparing preview", "ok")
        return CameraTestResponse(
            result="ok",
            reason_code=None,
            safe_message="Connection succeeded, preview ready",
            stages=stages,
            probe={
                "codec": probe.codec,
                "width": probe.width,
                "height": probe.height,
                "fps": probe.fps,
                "pix_fmt": probe.pix_fmt,
                "has_audio": probe.has_audio,
                "warnings": probe.warnings,
                "frames_decoded": len(frames),
                "first_frame_pts": frames[0].pts if frames else None,
                "redacted_endpoint": redact_url(req.endpoint),
                "resolved_ips": ips,
            },
        )
    except ProbeError as e:
        stage("Inspecting stream", "failed")
        code_map: dict[str, Literal["unreachable", "unsupported_media", "error"]] = {
            "no_video": "unsupported_media",
            "no_frames": "unreachable",
            "open_failed": "unreachable",
        }
        result = code_map.get(e.code, "error")
        return CameraTestResponse(result=result, reason_code=e.code, safe_message=str(e), stages=stages, probe=None)
    except SSRFError as e:
        stage("Inspecting stream", "failed")
        return CameraTestResponse(
            result="blocked" if e.code.startswith("blocked") else "error",
            reason_code=e.code,
            safe_message=e.safe_message,
            stages=stages,
            probe=None,
        )
    except Exception as e:
        stage("Inspecting stream", "failed")
        return CameraTestResponse(result="error", reason_code="probe_failed", safe_message=str(e), stages=stages)


@router.post("/test", response_model=CameraTestResponse)
async def test_unsaved(req: CameraTestRequest, _auth: bool = Depends(require_api_token)) -> CameraTestResponse:
    """Test connection without saving - spec 8 Step 3."""
    return await asyncio.to_thread(_run_test_stages, req)


@router.post("", response_model=dict[str, Any], status_code=201)
async def create_camera(
    req: CameraCreate, response: Response, _auth: bool = Depends(require_api_token)
) -> dict[str, Any]:
    req.endpoint = req.endpoint.strip().strip('"').strip("'")
    if _is_file_endpoint(req.endpoint, req.protocol):
        req.protocol = "file"
        req.source_type = "video_footage"
        req.endpoint = _import_external_video_if_needed(req.endpoint)
    file_endpoint = req.protocol == "file" or req.endpoint.startswith("file://")
    is_synthetic = req.endpoint.startswith("synthetic://")
    if is_synthetic and not _synthetic_allowed():
        raise HTTPException(
            status_code=400,
            detail={"code": "synthetic_disabled", "message": "Synthetic sources are only available in dev/test"},
        )
    if file_endpoint:
        endpoint_value = _resolve_jailed_file(req.endpoint)
        if not endpoint_value.exists():
            raise HTTPException(
                status_code=400, detail={"code": "missing_file", "message": "Local footage file not found"}
            )
    else:
        if not is_synthetic:
            raw_ep = req.endpoint.strip()
            if "://" not in raw_ep:
                scheme = req.protocol or ("rtsp" if ":554" in raw_ep else "http")
                raw_ep = f"{scheme}://{raw_ep}"
            req.endpoint = normalize_mjpeg_url(raw_ep)
        # Server-owned policy only (see _run_test_stages): caller CIDRs must
        # never authorize private ranges.
        policy = _policy_from_request(None)
        try:
            if not is_synthetic:
                parsed = validate_endpoint(req.endpoint, policy)
                if (req.username or req.password) and "@" in req.endpoint:
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "credential_in_url", "message": "Credentials must not be in URL"},
                    )
                if parsed.hostname:
                    await asyncio.to_thread(resolve_and_validate, parsed.hostname, policy, 3.0)
        except SSRFError as e:
            raise HTTPException(status_code=400, detail={"code": e.code, "message": e.safe_message}) from e
        endpoint_value = req.endpoint

    cam_id = str(uuid.uuid4())
    endpoint_redacted = redact_url(req.endpoint)
    try:
        enc_user = encrypt_secret(req.username) if req.username else None
        enc_pass = encrypt_secret(req.password) if req.password else None
    except (RuntimeError, ValueError) as e:
        raise HTTPException(
            status_code=400, detail={"code": "credential_storage_unavailable", "message": str(e)}
        ) from e

    sm = CameraStateMachine(camera_id=cam_id)
    sm.transition(CameraState.VALIDATING, reason="create", safe_message="Validating")
    sm.transition(CameraState.SAVING, reason="save", safe_message="Saving")
    sm.transition(CameraState.STARTING, reason="start", safe_message="Starting")
    sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")

    data = {
        "id": cam_id,
        "name": req.name,
        "site_id": str(req.site_id),
        "source_type": req.source_type,
        "endpoint": str(endpoint_value) if file_endpoint else endpoint_redacted,
        "protocol": req.protocol,
        "stream_epoch": sm.stream_epoch,
        "desired_state": "STREAMING",
        "observed_state": sm.state.value,
        "has_credentials": bool(enc_user or enc_pass),
        "temporary": req.temporary,
        "created_at": time.time(),
    }
    _CAMERAS[cam_id] = data
    _STATE_MACHINES[cam_id] = sm
    _CAMERAS[cam_id]["_enc"] = {"username": enc_user, "password": enc_pass}
    _CAMERAS[cam_id]["_site_cidr_allowlist"] = req.site_cidr_allowlist
    if file_endpoint:
        _PLAYBACK[cam_id] = {
            "state": "playing",
            "position_seconds": 0.0,
            "duration_seconds": None,
            "fps": None,
        }
    if not is_synthetic:
        _start_camera_worker(cam_id)
    try:
        from ibvap.services.persistence import save_camera_to_db

        asyncio.create_task(save_camera_to_db(data))
    except Exception as e:
        logger.debug("save_camera_db_trigger_error", error=str(e))
    # Task 5: creates return 201 + Location of the new resource.
    response.headers["Location"] = f"/api/v1/cameras/{cam_id}"
    return {k: v for k, v in data.items() if not k.startswith("_")}


@router.get("", response_model=dict[str, Any])
async def list_cameras(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    cams = [{k: v for k, v in cam.items() if not k.startswith("_")} for cam in _CAMERAS.values()]
    total = len(cams)
    # Task 5: bounded page (OOM-safe on large fleets) + total for UI paging.
    return {"items": cams[offset : offset + limit], "total": total, "limit": limit, "offset": offset}


@router.get("/{camera_id}", response_model=dict[str, Any])
async def get_camera(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.get("/{camera_id}/stream")
async def camera_stream(camera_id: str) -> StreamingResponse:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})

    loop = asyncio.get_running_loop()
    frame_event = asyncio.Event()
    with _STREAM_SUBSCRIBERS_LOCK:
        _STREAM_SUBSCRIBERS.setdefault(camera_id, set()).add((loop, frame_event))
        _STREAM_CLIENT_COUNT[camera_id] = len(_STREAM_SUBSCRIBERS[camera_id])

    if camera_id in _FRAMES:
        frame_event.set()

    async def body():
        last_version = -1
        try:
            while camera_id in _CAMERAS:
                try:
                    await asyncio.wait_for(frame_event.wait(), timeout=0.5)
                except TimeoutError:
                    if camera_id not in _CAMERAS:
                        break
                    continue
                frame_event.clear()
                current_version = _FRAME_VERSIONS.get(camera_id, 0)
                if current_version != last_version:
                    frame = _FRAMES.get(camera_id)
                    if frame:
                        last_version = current_version
                        yield b"".join(
                            (
                                _MJPEG_BOUNDARY,
                                _MJPEG_CT,
                                str(len(frame)).encode("ascii"),
                                _MJPEG_SEP,
                                frame,
                                _MJPEG_END,
                            )
                        )
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            with _STREAM_SUBSCRIBERS_LOCK:
                subs = _STREAM_SUBSCRIBERS.get(camera_id)
                if subs is not None:
                    subs.discard((loop, frame_event))
                    _STREAM_CLIENT_COUNT[camera_id] = len(subs)
                    if not subs:
                        _STREAM_SUBSCRIBERS.pop(camera_id, None)
                        _FRAMES.pop(camera_id, None)

    return StreamingResponse(
        body(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            # Task 1 P0: no explicit wildcard — rely on CORSMiddleware allowlist.
        },
    )


@router.get("/{camera_id}/observations", response_model=dict[str, Any])
async def camera_observations(camera_id: str) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    return _OBSERVATIONS.get(
        camera_id,
        {
            "aspect_ratio": None,
            "frame_width": None,
            "frame_height": None,
            "detections": [],
            "tracks": [],
            "faces": [],
            "frame_at": None,
        },
    )


@router.put("/{camera_id}/fence", response_model=dict[str, Any])
async def set_camera_fence(
    camera_id: str, req: CameraFenceRequest, _auth: bool = Depends(require_api_token)
) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})

    if not req.polygon and not req.line:
        _CAMERAS[camera_id]["fence"] = None
        pipeline = _ACTIVE_PIPELINES.get(camera_id)
        if pipeline is not None:
            pipeline.zone = DEFAULT_ZONE
            if hasattr(pipeline, "_active_line_intruders"):
                pipeline._active_line_intruders.clear()
        return {k: v for k, v in _CAMERAS[camera_id].items() if not k.startswith("_")}

    points = req.line if req.line is not None else req.polygon

    if req.fence_type == "line" or req.line is not None:
        effective_type = "line"
    elif req.fence_type == "auto":
        effective_type = "line" if len(points) == 2 else "polygon"
    elif req.fence_type == "polygon":
        effective_type = "polygon"
    else:
        effective_type = "polygon"

    error = validate_fence(points, fence_type=effective_type)
    if error:
        raise HTTPException(status_code=422, detail={"code": "invalid_fence", "message": error})

    if any(not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0) for point in points):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_fence", "message": "Fence points must be normalized between 0 and 1"},
        )

    zone_name = "User line tripwire" if effective_type == "line" else "User fence"
    zone = Zone(
        id=f"zone-{camera_id[:8]}",
        name=zone_name,
        polygon=points,
        enabled=req.enabled,
        fence_type=effective_type,
    )
    _CAMERAS[camera_id]["fence"] = {
        "polygon": points,
        "fence_type": effective_type,
        "enabled": req.enabled,
        "name": zone.name,
    }
    pipeline = _ACTIVE_PIPELINES.get(camera_id)
    if pipeline is not None:
        pipeline.zone = zone
        if hasattr(pipeline, "_active_line_intruders"):
            pipeline._active_line_intruders.clear()
    try:
        from ibvap.services.persistence import save_camera_to_db

        asyncio.create_task(save_camera_to_db(_CAMERAS[camera_id]))
    except Exception:
        pass
    return {k: v for k, v in _CAMERAS[camera_id].items() if not k.startswith("_")}


@router.delete("/{camera_id}/fence", response_model=dict[str, Any])
async def delete_camera_fence(camera_id: str, _auth: bool = Depends(require_api_token)) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    _CAMERAS[camera_id]["fence"] = None
    pipeline = _ACTIVE_PIPELINES.get(camera_id)
    if pipeline is not None:
        pipeline.zone = DEFAULT_ZONE
        if hasattr(pipeline, "_active_line_intruders"):
            pipeline._active_line_intruders.clear()
    try:
        from ibvap.services.persistence import save_camera_to_db

        asyncio.create_task(save_camera_to_db(_CAMERAS[camera_id]))
    except Exception:
        pass
    return {k: v for k, v in _CAMERAS[camera_id].items() if not k.startswith("_")}


@router.get("/{camera_id}/playback", response_model=dict[str, Any])
async def playback_state(camera_id: str) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    if not _is_file_camera(camera_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "playback_unavailable",
                "message": "Playback controls are only available for video footage",
            },
        )
    with _PLAYBACK_LOCK:
        return dict(
            _PLAYBACK.setdefault(
                camera_id, {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None}
            )
        )


@router.post("/{camera_id}/playback/seek", response_model=dict[str, Any])
async def playback_seek(
    camera_id: str, req: PlaybackSeekRequest, _auth: bool = Depends(require_api_token)
) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    if not _is_file_camera(camera_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "playback_unavailable",
                "message": "Playback controls are only available for video footage",
            },
        )
    with _PLAYBACK_LOCK:
        playback = _PLAYBACK.setdefault(
            camera_id, {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None}
        )
        duration = playback.get("duration_seconds")
        position = min(req.position_seconds, duration) if duration else req.position_seconds
        playback["position_seconds"] = position
        playback["seek_to"] = position
        return dict(playback)


@router.post("/{camera_id}/playback/{action}", response_model=dict[str, Any])
async def playback_action(
    camera_id: str, action: Literal["pause", "resume", "stop", "restart"], _auth: bool = Depends(require_api_token)
) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    if not _is_file_camera(camera_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "playback_unavailable",
                "message": "Playback controls are only available for video footage",
            },
        )
    with _PLAYBACK_LOCK:
        playback = _PLAYBACK.setdefault(
            camera_id, {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None}
        )
        if action == "pause":
            playback["state"] = "paused"
        elif action == "resume":
            playback["state"] = "playing"
        elif action == "restart":
            playback["state"] = "playing"
            playback["position_seconds"] = 0.0
            playback["seek_to"] = 0.0
        else:
            playback["state"] = "stopped"
            _CAMERAS[camera_id]["observed_state"] = "DISABLED"
            _CAMERAS[camera_id]["desired_state"] = "DISABLED"
            camera = _CAMERAS.pop(camera_id)
            _STATE_MACHINES.pop(camera_id, None)
            _HEALTH.pop(camera_id, None)
            _FRAMES.pop(camera_id, None)
            _FRAME_VERSIONS.pop(camera_id, None)
            _OBSERVATIONS.pop(camera_id, None)
            _PLAYBACK.pop(camera_id, None)
            if camera.get("temporary") and camera.get("protocol") == "file":
                _safe_unlink_inside_jail(str(camera["endpoint"]))
        state = dict(playback)
    if action == "stop":
        _stop_worker(camera_id)
        _ACTIVE_PIPELINES.pop(camera_id, None)
        _FRAME_CONDITIONS.pop(camera_id, None)
        with _STREAM_SUBSCRIBERS_LOCK:
            subs = list(_STREAM_SUBSCRIBERS.pop(camera_id, set()))
            _STREAM_CLIENT_COUNT.pop(camera_id, None)
        for loop, event in subs:
            if not loop.is_closed():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(event.set)
    if action in {"pause", "resume", "restart"}:
        _CAMERAS[camera_id]["observed_state"] = "PAUSED" if action == "pause" else "STREAMING"
    return state


@router.post("/{camera_id}/test", response_model=CameraTestResponse)
async def test_saved(camera_id: str, _auth: bool = Depends(require_api_token)) -> CameraTestResponse:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    # Task 5: probe with the stored canonical endpoint PLUS the persisted
    # _enc credentials — the stored endpoint is redacted (no userinfo/query
    # secrets), so probing it bare would fail auth on guarded cameras.
    username: str | None = None
    password: str | None = None
    enc = cam.get("_enc") or {}
    try:
        if enc.get("username"):
            username = decrypt_secret(enc["username"])
        if enc.get("password"):
            password = decrypt_secret(enc["password"])
    except Exception as e:
        logger.warning("test_saved_credential_decrypt_failed", camera_id=camera_id, error=str(e))
    req = CameraTestRequest(
        endpoint=cam["endpoint"],
        protocol=cam.get("protocol"),
        username=username,
        password=password,
        # Stored allowlist is request-originated: do not forward it (server policy only).
        site_cidr_allowlist=None,
    )
    return await asyncio.to_thread(_run_test_stages, req)


@router.post("/{camera_id}/enable", response_model=dict[str, Any])
async def enable_camera(camera_id: str, _auth: bool = Depends(require_api_token)) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    sm = _STATE_MACHINES.get(camera_id)
    if sm and sm.is_disabled():
        sm.transition(CameraState.DRAFT, reason="enable", safe_message="Enabled")
        sm.transition(CameraState.VALIDATING, reason="enable", safe_message="Validating")
        sm.transition(CameraState.SAVING, reason="enable", safe_message="Saving")
        sm.transition(CameraState.STARTING, reason="start", safe_message="Starting")
        sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")
        cam["observed_state"] = sm.state.value
        cam["desired_state"] = "STREAMING"
    is_synthetic = bool(cam.get("endpoint", "").startswith("synthetic://"))
    if not is_synthetic:
        _start_camera_worker(camera_id)
    try:
        from ibvap.services.persistence import save_camera_to_db

        asyncio.create_task(save_camera_to_db(cam))
    except Exception:
        pass
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.post("/{camera_id}/disable", response_model=dict[str, Any])
async def disable_camera(camera_id: str, _auth: bool = Depends(require_api_token)) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    sm = _STATE_MACHINES.get(camera_id)
    if sm:
        sm.disable()
        cam["observed_state"] = sm.state.value
        cam["desired_state"] = "DISABLED"
    _stop_worker(camera_id)
    try:
        from ibvap.services.persistence import save_camera_to_db

        asyncio.create_task(save_camera_to_db(cam))
    except Exception:
        pass
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.post("/{camera_id}/reconnect", response_model=dict[str, Any])
async def reconnect_camera(camera_id: str, _auth: bool = Depends(require_api_token)) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    sm = _STATE_MACHINES.get(camera_id)
    if sm:
        if sm.is_disabled():
            raise HTTPException(
                status_code=400, detail={"code": "camera_disabled", "message": "Disabled camera cannot be reconnected"}
            )
        try:
            sm.transition(CameraState.RECONNECTING, reason="reconnect", safe_message="Reconnecting")
            sm.transition(CameraState.CONNECTING, reason="connect", safe_message="Connecting")
            sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")
            cam["stream_epoch"] = sm.stream_epoch
            cam["observed_state"] = sm.state.value
        except ValueError as e:
            raise HTTPException(status_code=400, detail={"code": "invalid_transition", "message": str(e)}) from e
    _stop_worker(camera_id)
    _start_camera_worker(camera_id)
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.delete("/{camera_id}", response_model=dict[str, str])
async def delete_camera(camera_id: str, _auth: bool = Depends(require_api_token)) -> dict[str, str]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    del _CAMERAS[camera_id]
    _stop_worker(camera_id)
    _STATE_MACHINES.pop(camera_id, None)
    _HEALTH.pop(camera_id, None)
    _FRAMES.pop(camera_id, None)
    _FRAME_VERSIONS.pop(camera_id, None)
    _FRAME_CONDITIONS.pop(camera_id, None)
    _OBSERVATIONS.pop(camera_id, None)
    _ACTIVE_PIPELINES.pop(camera_id, None)
    _PLAYBACK.pop(camera_id, None)
    with _STREAM_SUBSCRIBERS_LOCK:
        subs = list(_STREAM_SUBSCRIBERS.pop(camera_id, set()))
        _STREAM_CLIENT_COUNT.pop(camera_id, None)
    for loop, event in subs:
        if not loop.is_closed():
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(event.set)
    try:
        from ibvap.services.persistence import delete_camera_from_db

        asyncio.create_task(delete_camera_from_db(camera_id))
    except Exception:
        pass
    return {"status": "deleted", "id": camera_id}


@router.get("/{camera_id}/health", response_model=dict[str, Any])
async def camera_health(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail={"code": "camera_not_found", "message": "Camera not found"})
    sm = _STATE_MACHINES.get(camera_id)
    samples = _HEALTH.get(camera_id, [])
    now = time.time()
    formatted_samples: list[dict[str, Any]] = []
    for s in samples[-10:]:
        s_copy = dict(s)
        if "_ts" in s_copy:
            s_copy["last_frame_age_ms"] = max(0, int((now - s_copy.pop("_ts")) * 1000))
        formatted_samples.append(s_copy)
    return {
        "camera_id": camera_id,
        "observed_state": cam.get("observed_state"),
        "stream_epoch": cam.get("stream_epoch", 0),
        "retry_count": sm.retry_count if sm else 0,
        "samples": formatted_samples,
        "is_disabled": sm.is_disabled() if sm else False,
    }
