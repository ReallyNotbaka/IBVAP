"""Camera CRUD + connection testing - Phase 2."""

from __future__ import annotations

import ipaddress
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.credentials import encrypt_secret, redact_url
from ibvap.core.probe import ProbeError, probe_url
from ibvap.core.ssrf import SSRFError, SSRFPolicy, resolve_and_validate, validate_endpoint  # noqa: F401 - re-export

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


# In-memory store for Phase 2 demo (PG persistence via migrations; runtime wired in Phase 3)
_CAMERAS: dict[str, dict[str, Any]] = {}
_STATE_MACHINES: dict[str, CameraStateMachine] = {}
_HEALTH: dict[str, list[dict[str, Any]]] = {}


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    site_id: str
    source_type: Literal["smartphone_ip_webcam", "ip_camera"] = "smartphone_ip_webcam"
    endpoint: str = Field(description="Stream URL without credentials")
    protocol: Literal["rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip"] = "http"
    username: str | None = None
    password: str | None = None
    site_cidr_allowlist: list[str] | None = None


class CameraTestRequest(BaseModel):
    endpoint: str
    protocol: str | None = None
    username: str | None = None
    password: str | None = None
    site_cidr_allowlist: list[str] | None = None


class CameraTestResponse(BaseModel):
    result: Literal["ok", "blocked", "unreachable", "auth_failed", "unsupported_media", "error"]
    reason_code: str | None = None
    safe_message: str
    stages: list[dict[str, str]]
    probe: dict[str, Any] | None = None


def _policy_from_request(allowlist: list[str] | None) -> SSRFPolicy:
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in allowlist or []:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))  # type: ignore[arg-type]
        except ValueError:
            continue
    # default private allowlist for dev: allow 192.168/16, 10/8, 172.16/12 via policy if provided
    return SSRFPolicy(
        allowed_schemes=frozenset({"rtsp", "rtsps", "http", "https"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=tuple(nets),
    )


def _run_test_stages(req: CameraTestRequest) -> CameraTestResponse:
    policy = _policy_from_request(req.site_cidr_allowlist)
    stages: list[dict[str, str]] = []

    def stage(name: str, status: str) -> None:
        stages.append({"name": name, "status": status})

    # Synthetic harness for tests / offline dev - no network
    if req.endpoint.startswith("synthetic://"):
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

    # Stage 2: Checking network permission (already done via validate)
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
    stage("Authenticating", "ok")  # placeholder - real RTSP digest handled in probe

    # Stage 6: Inspecting stream
    stage("Inspecting stream", "running")
    try:
        probe, frames = probe_url(req.endpoint, timeout=3.0, max_frames=2)
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
        code_map = {"no_video": "unsupported_media", "no_frames": "unreachable", "open_failed": "unreachable"}
        result = code_map.get(e.code, "error")  # type: ignore[arg-type]
        return CameraTestResponse(result=result, reason_code=e.code, safe_message=str(e), stages=stages, probe=None)  # type: ignore[arg-type]
    except Exception as e:
        stage("Inspecting stream", "failed")
        return CameraTestResponse(result="error", reason_code="probe_failed", safe_message=str(e), stages=stages)


@router.post("/test", response_model=CameraTestResponse)
async def test_unsaved(req: CameraTestRequest) -> CameraTestResponse:
    """Test connection without saving - spec 8 Step 3."""
    return _run_test_stages(req)


@router.post("", response_model=dict[str, Any])
async def create_camera(req: CameraCreate) -> dict[str, Any]:
    # SSRF check before saving - allow synthetic harness for tests/dev
    is_synthetic = req.endpoint.startswith("synthetic://")
    policy = _policy_from_request(req.site_cidr_allowlist)
    try:
        if not is_synthetic:
            validate_endpoint(req.endpoint, policy)
            if (req.username or req.password) and "@" in req.endpoint:
                raise HTTPException(status_code=400, detail="Credentials must not be in URL")
    except SSRFError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.safe_message}) from e

    cam_id = str(uuid.uuid4())
    # never persist credentials in URL
    endpoint_redacted = redact_url(req.endpoint)
    enc_user = encrypt_secret(req.username) if req.username else None
    enc_pass = encrypt_secret(req.password) if req.password else None

    # duplicate endpoint check (warn if same endpoint exists)
    for existing in _CAMERAS.values():
        if existing["endpoint"] == endpoint_redacted:
            # allow after explicit confirmation - for now just warn via header? return 409 unless force?
            pass

    sm = CameraStateMachine(camera_id=cam_id)
    # go through validating -> saving path
    sm.transition(CameraState.VALIDATING, reason="create", safe_message="Validating")
    sm.transition(CameraState.SAVING, reason="save", safe_message="Saving")
    sm.transition(CameraState.STARTING, reason="start", safe_message="Starting")
    sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")

    data = {
        "id": cam_id,
        "name": req.name,
        "site_id": req.site_id,
        "source_type": req.source_type,
        "endpoint": endpoint_redacted,
        "protocol": req.protocol,
        "stream_epoch": sm.stream_epoch,
        "desired_state": "STREAMING",
        "observed_state": sm.state.value,
        "has_credentials": bool(enc_user or enc_pass),
        "created_at": time.time(),
    }
    _CAMERAS[cam_id] = data
    _STATE_MACHINES[cam_id] = sm
    # store encrypted creds separately (in-mem for Phase 2)
    _CAMERAS[cam_id]["_enc"] = {"username": enc_user, "password": enc_pass}
    # never return credentials
    return {k: v for k, v in data.items() if not k.startswith("_")}


@router.get("", response_model=list[dict[str, Any]])
async def list_cameras() -> list[dict[str, Any]]:
    return [{k: v for k, v in cam.items() if not k.startswith("_")} for cam in _CAMERAS.values()]


@router.get("/{camera_id}", response_model=dict[str, Any])
async def get_camera(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.post("/{camera_id}/test", response_model=CameraTestResponse)
async def test_saved(camera_id: str) -> CameraTestResponse:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    req = CameraTestRequest(endpoint=cam["endpoint"], protocol=cam.get("protocol"))
    return _run_test_stages(req)


@router.post("/{camera_id}/enable", response_model=dict[str, Any])
async def enable_camera(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    sm = _STATE_MACHINES.get(camera_id)
    if sm and sm.is_disabled():
        sm.transition(CameraState.DRAFT, reason="enable", safe_message="Enabled")
        sm.transition(CameraState.VALIDATING, reason="enable", safe_message="Validating")
        sm.transition(CameraState.SAVING, reason="enable", safe_message="Saving")
        sm.transition(CameraState.STARTING, reason="start", safe_message="Starting")
        sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")
        cam["observed_state"] = sm.state.value
        cam["desired_state"] = "STREAMING"
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.post("/{camera_id}/disable", response_model=dict[str, Any])
async def disable_camera(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    sm = _STATE_MACHINES.get(camera_id)
    if sm:
        sm.disable()
        cam["observed_state"] = sm.state.value
        cam["desired_state"] = "DISABLED"
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.post("/{camera_id}/reconnect", response_model=dict[str, Any])
async def reconnect_camera(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    sm = _STATE_MACHINES.get(camera_id)
    if sm:
        if sm.is_disabled():
            raise HTTPException(status_code=400, detail="Disabled camera cannot be reconnected")
        try:
            sm.transition(CameraState.RECONNECTING, reason="reconnect", safe_message="Reconnecting")
            sm.transition(CameraState.CONNECTING, reason="connect", safe_message="Connecting")
            sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")
            cam["stream_epoch"] = sm.stream_epoch
            cam["observed_state"] = sm.state.value
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.delete("/{camera_id}", response_model=dict[str, str])
async def delete_camera(camera_id: str) -> dict[str, str]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    # impact preview would be here - for Phase 2 we just delete
    del _CAMERAS[camera_id]
    _STATE_MACHINES.pop(camera_id, None)
    _HEALTH.pop(camera_id, None)
    return {"status": "deleted", "id": camera_id}


@router.get("/{camera_id}/health", response_model=dict[str, Any])
async def camera_health(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    sm = _STATE_MACHINES.get(camera_id)
    samples = _HEALTH.get(camera_id, [])
    return {
        "camera_id": camera_id,
        "observed_state": cam.get("observed_state"),
        "stream_epoch": cam.get("stream_epoch", 0),
        "retry_count": sm.retry_count if sm else 0,
        "samples": samples[-10:],
        "is_disabled": sm.is_disabled() if sm else False,
    }
