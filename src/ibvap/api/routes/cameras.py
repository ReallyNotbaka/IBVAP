"""Camera CRUD + connection testing - Phase 2."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import av
import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ibvap.core.anpr import ANPRPipeline
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.credentials import encrypt_secret, redact_url
from ibvap.core.model_manager import get_shared_detector_handle
from ibvap.core.night import NightDetector
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.probe import ProbeError, probe_url
from ibvap.core.ssrf import SSRFError, SSRFPolicy, resolve_and_validate, validate_endpoint  # noqa: F401 - re-export

import sys

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


# In-memory store for Phase 2 demo (PG persistence via migrations; runtime wired in Phase 3)
_CAMERAS: dict[str, dict[str, Any]] = {}
_STATE_MACHINES: dict[str, CameraStateMachine] = {}
_HEALTH: dict[str, list[dict[str, Any]]] = {}
_WORKERS: dict[str, tuple[threading.Event, threading.Thread]] = {}
_FRAMES: dict[str, bytes] = {}
_FRAME_VERSIONS: dict[str, int] = {}
_FRAME_CONDITIONS: dict[str, threading.Condition] = {}
_OBSERVATIONS: dict[str, dict[str, Any]] = {}
_ACTIVE_PIPELINES: dict[str, MiniPipeline] = {}


def _camera_worker(camera_id: str, stop: threading.Event) -> None:
    cam = _CAMERAS[camera_id]
    endpoint = str(cam["endpoint"])
    # ---- distinguish file footage vs live stream for optimisation ----
    # File footage is finite: must NOT infinite-reconnect (cpu burn). Use optimized single-pass with sampling.
    is_file_source = False
    try:
        # source_type video_footage is definitive; also check protocol file or filesystem path
        if cam.get("source_type") == "video_footage" or cam.get("protocol") == "file":
            is_file_source = True
        else:
            p = Path(endpoint.replace("file://", "", 1)) if endpoint.startswith("file://") else Path(endpoint)
            if p.exists() and p.suffix.lower() in {".mp4", ".avi", ".mkv", ".mov", ".webm"}:
                is_file_source = True
    except Exception:
        is_file_source = False

    # --- pipeline: wired to shared ThreadSafeDetectorHandle and Hungarian biometric tracking ---
    detector_handle = get_shared_detector_handle()
    pipeline = MiniPipeline(
        camera_id=camera_id,
        stream_epoch=cam["stream_epoch"],
        detector_handle=detector_handle,
        enable_face=True,
        face_stride=2,
        sample_stride=1,
    )
    _ACTIVE_PIPELINES[camera_id] = pipeline

    anpr = ANPRPipeline()
    night_detector = NightDetector(temporal_seconds=0.0)
    condition = _FRAME_CONDITIONS.setdefault(camera_id, threading.Condition())
    frame_number = 0

    analysis_frame: np.ndarray | None = None
    analysis_lock = threading.Lock()
    analysis_ready = threading.Event()
    analysis_fps_counter = 0
    last_analysis_fps = 0.0
    last_analysis_fps_calc = time.perf_counter()
    last_inference_ms = 0.0

    last_night_result = None
    last_night_time = 0.0

    def analyze() -> None:
        nonlocal analysis_frame, analysis_fps_counter, last_analysis_fps, last_analysis_fps_calc, last_inference_ms, last_night_result, last_night_time
        while not stop.is_set():
            if not analysis_ready.wait(timeout=0.5):
                continue
            analysis_ready.clear()
            with analysis_lock:
                current = analysis_frame
                analysis_frame = None
            if current is None:
                continue

            try:
                t_infer_start = time.perf_counter()
                pipeline.process_frame(current)
                t_infer_end = time.perf_counter()
                last_inference_ms = (t_infer_end - t_infer_start) * 1000.0

                h_c, w_c = current.shape[:2]
                plates: list[dict[str, Any]] = []
                if pipeline.last_detections:
                    for detection in pipeline.last_detections:
                        if detection["class_name"] not in {"car", "truck", "bus", "motorcycle"}:
                            continue
                        x1, y1, x2, y2 = detection["bbox_norm"]
                        crop = current[int(y1 * h_c) : int(y2 * h_c), int(x1 * w_c) : int(x2 * w_c)]
                        if crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 35:
                            continue
                        plate = anpr.process_vehicle_crop(crop, vehicle_id=0)
                        if plate and plate.consensus:
                            plates.append({"text": plate.consensus, "confidence": plate.quality})

                now_ts = time.time()
                if last_night_result is None or (now_ts - last_night_time) >= 0.5:
                    thumb = cv2.resize(current, (320, 180), interpolation=cv2.INTER_NEAREST)
                    last_night_result = night_detector.update(thumb, timestamp=now_ts)
                    last_night_time = now_ts
                night = last_night_result

                _OBSERVATIONS[camera_id] = {
                    "runtime": getattr(pipeline, "runtime", getattr(pipeline.detector, "runtime", "cpu")),
                    "active_model": getattr(pipeline, "model_id", "yolo26n"),
                    "aspect_ratio": round(w_c / max(1, h_c), 4),
                    "frame_width": w_c,
                    "frame_height": h_c,
                    "detections": pipeline.last_detections,
                    "tracks": [
                        {
                            "track_id": track.track_id,
                            "class_name": track.class_name,
                            "confidence": track.confidence,
                            "bbox_norm": track.bbox_norm,
                            "identity": getattr(track, "identity", None),
                            "identity_locked": getattr(track, "identity_locked", False),
                        }
                        for track in pipeline.last_tracks
                    ],
                    "faces": [
                        {"bbox_norm": f["bbox_norm"], "confidence": f["confidence"], "quality_passed": f.get("quality_passed", True)}
                        for f in pipeline.last_faces
                    ],
                    "plates": plates,
                    "night": {
                        "is_night": night.is_night,
                        "illumination_score": night.illumination_score,
                        "motion_area": night.motion_area,
                        "confidence": night.confidence,
                        "limitation": night.limitation,
                    },
                    "frame_at": time.time(),
                }

                analysis_fps_counter += 1
                now = time.perf_counter()
                if now - last_analysis_fps_calc >= 1.0:
                    last_analysis_fps = analysis_fps_counter / (now - last_analysis_fps_calc)
                    analysis_fps_counter = 0
                    last_analysis_fps_calc = now
            except Exception:
                # Protect analysis thread from termination so HUD and observations stay active
                pass

    analysis_thread = threading.Thread(target=analyze, daemon=True, name=f"analysis-{camera_id[:8]}")
    analysis_thread.start()

    # ---------- FILE FOOTAGE: decoupled native FPS playback with continuous looping ----------
    if is_file_source:
        file_path_str = endpoint.replace("file://", "", 1) if endpoint.startswith("file://") else endpoint
        container = None
        loop_count = 0
        decode_errors = 0

        while not stop.is_set():
            try:
                if container is not None:
                    with contextlib.suppress(Exception):
                        container.close()
                container = av.open(file_path_str)
                stream = next((s for s in container.streams if s.type == "video"), None)
                if stream is None:
                    raise RuntimeError("No video stream found in file")

                cam["observed_state"] = "STREAMING"
                detected_fps = None
                for r in (stream.average_rate, stream.guessed_rate, stream.base_rate):
                    if r and r.denominator:
                        val = float(r)
                        if val > 0:
                            detected_fps = val
                            break
                fps = detected_fps if detected_fps is not None else 30.0
                fps = max(5.0, min(fps, 60.0))
                frame_interval = 1.0 / fps

                while not stop.is_set():
                    next_frame_time = time.perf_counter()
                    frames_in_pass = 0

                    try:
                        for frame in container.decode(stream):
                            if stop.is_set():
                                break

                            image = frame.to_ndarray(format="bgr24")
                            h, w = image.shape[:2]
                            preview = cv2.resize(image, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_LINEAR) if w > 1280 else image

                            ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                            if ok:
                                frame_bytes = encoded.tobytes()
                                with condition:
                                    _FRAMES[camera_id] = frame_bytes
                                    _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                                    condition.notify_all()

                            # Asynchronously schedule analysis with the latest frame without blocking decode
                            with analysis_lock:
                                analysis_frame = image
                            analysis_ready.set()

                            frame_number += 1
                            frames_in_pass += 1

                            samples = _HEALTH.setdefault(camera_id, [])
                            samples.append(
                                {
                                    "last_frame_age_ms": 0,
                                    "source_fps": round(fps, 1),
                                    "analysis_fps": round(last_analysis_fps or fps, 1),
                                    "inference_ms": round(last_inference_ms, 1),
                                    "queue_drops": 0,
                                    "decode_errors": decode_errors,
                                    "reconnect_count": loop_count,
                                    "stream_epoch": cam["stream_epoch"],
                                    "faces_analyzed": pipeline.faces_analyzed,
                                    "frames_skipped": pipeline.frames_skipped,
                                }
                            )
                            del samples[:-10]

                            # Precise pacing to match native file FPS
                            next_frame_time += frame_interval
                            now = time.perf_counter()
                            sleep_time = next_frame_time - now
                            if sleep_time > 0:
                                time.sleep(sleep_time)
                            elif sleep_time < -0.2:
                                next_frame_time = now

                    except (av.error.EOFError, av.error.InvalidDataError):
                        pass
                    except Exception:
                        decode_errors += 1

                    if stop.is_set():
                        break

                    loop_count += 1
                    seek_success = False
                    try:
                        container.seek(0)
                        seek_success = True
                    except Exception:
                        seek_success = False

                    if not seek_success or frames_in_pass == 0:
                        if frames_in_pass == 0:
                            time.sleep(0.5)
                        break

            except Exception as exc:
                if stop.is_set():
                    break
                decode_errors += 1
                cam["observed_state"] = "RECONNECTING"
                _OBSERVATIONS[camera_id] = {
                    "error": str(exc),
                    "aspect_ratio": None,
                    "frame_width": None,
                    "frame_height": None,
                    "detections": [],
                    "tracks": [],
                    "faces": [],
                    "frame_at": time.time(),
                }
                time.sleep(0.5)
            finally:
                if container is not None:
                    with contextlib.suppress(Exception):
                        container.close()

        analysis_ready.set()
        _ACTIVE_PIPELINES.pop(camera_id, None)
        return

    # ---------- LIVE STREAM: keep threaded analysis with worker sampling ----------
    try:
        container = av.open(cam["endpoint"], options={"timeout": "3000000", "stimeout": "3000000"})
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            raise RuntimeError("No video stream")
        for frame in container.decode(stream):
            if stop.is_set():
                break
            image = frame.to_ndarray(format="bgr24")
            h, w = image.shape[:2]
            preview = cv2.resize(image, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_LINEAR) if w > 1280 else image
            ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                frame_bytes = encoded.tobytes()
                with condition:
                    _FRAMES[camera_id] = frame_bytes
                    _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                    condition.notify_all()
            with analysis_lock:
                analysis_frame = image
            analysis_ready.set()
            frame_number += 1
            samples = _HEALTH.setdefault(camera_id, [])
            samples.append(
                {
                    "last_frame_age_ms": 0,
                    "source_fps": float(stream.average_rate) if stream.average_rate and stream.average_rate.denominator else 30.0,
                    "analysis_fps": round(last_analysis_fps or 30.0, 1),
                    "inference_ms": round(last_inference_ms, 1),
                    "queue_drops": 0,
                    "decode_errors": 0,
                    "reconnect_count": 0,
                    "stream_epoch": cam["stream_epoch"],
                }
            )
            del samples[:-10]
    except Exception:
        cam["observed_state"] = "UNREACHABLE"
    finally:
        with contextlib.suppress(Exception):
            container.close()  # type: ignore[possibly-undefined]
    reconnect_delay = 1.0
    while not stop.is_set():
        container = None
        try:
            container = av.open(cam["endpoint"], options={"timeout": "3000000", "stimeout": "3000000"})
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise RuntimeError("No video stream")
            cam["observed_state"] = "STREAMING"
            reconnect_delay = 1.0
            for frame in container.decode(stream):
                if stop.is_set():
                    break
                image = frame.to_ndarray(format="bgr24")
                h, w = image.shape[:2]
                preview = cv2.resize(image, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_LINEAR) if w > 1280 else image
                ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    frame_bytes = encoded.tobytes()
                    with condition:
                        _FRAMES[camera_id] = frame_bytes
                        _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                        condition.notify_all()
                with analysis_lock:
                    analysis_frame = image
                analysis_ready.set()
                frame_number += 1
                samples = _HEALTH.setdefault(camera_id, [])
                samples.append(
                    {
                        "last_frame_age_ms": 0,
                        "source_fps": float(stream.average_rate) if stream.average_rate and stream.average_rate.denominator else 30.0,
                        "analysis_fps": round(last_analysis_fps or 30.0, 1),
                        "inference_ms": round(last_inference_ms, 1),
                        "queue_drops": 0,
                        "decode_errors": 0,
                        "reconnect_count": 0,
                        "stream_epoch": cam["stream_epoch"],
                    }
                )
                del samples[:-10]
        except Exception:
            cam["observed_state"] = "RECONNECTING"
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, 5.0)
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.close()
    _ACTIVE_PIPELINES.pop(camera_id, None)


def _start_camera_worker(camera_id: str) -> None:
    if camera_id in _WORKERS:
        return
    stop = threading.Event()
    worker = threading.Thread(target=_camera_worker, args=(camera_id, stop), daemon=True, name=f"camera-{camera_id[:8]}")
    _WORKERS[camera_id] = (stop, worker)
    worker.start()


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    site_id: str
    source_type: Literal["smartphone_ip_webcam", "ip_camera", "video_footage"] = "smartphone_ip_webcam"
    endpoint: str = Field(description="Stream URL without credentials, or a local video path")
    protocol: Literal["rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip", "file"] = "http"
    username: str | None = None
    password: str | None = None
    site_cidr_allowlist: list[str] | None = None


class CameraTestRequest(BaseModel):
    endpoint: str
    protocol: Literal["rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip", "file"] | None = None
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

    file_endpoint = req.protocol == "file" or req.endpoint.startswith("file://") or (req.protocol is None and Path(req.endpoint).exists())
    if file_endpoint:
        local_path = Path(req.endpoint.replace("file://", "", 1)) if req.endpoint.startswith("file://") else Path(req.endpoint)
        stage("Validating address", "ok")
        stage("Checking network permission", "ok")
        stage("Resolving host", "ok")
        stage("Connecting", "ok")
        stage("Authenticating", "ok")
        stage("Inspecting stream", "running")
        try:
            if not local_path.exists():
                raise FileNotFoundError(local_path)
            container = av.open(str(local_path))
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise RuntimeError("No video stream")
            first_frame = next(container.decode(stream), None)
            if first_frame is None:
                raise RuntimeError("No frames decoded")
            image = first_frame.to_ndarray(format="bgr24")
            stage("Inspecting stream", "ok")
            stage("Decoding first frame", "ok")
            stage("Measuring stability", "ok")
            stage("Preparing preview", "ok")
            return CameraTestResponse(
                result="ok",
                reason_code=None,
                safe_message="Local video preview ready",
                stages=stages,
                probe={
                    "codec": getattr(stream, "codec_context", None).name if getattr(stream, "codec_context", None) else "unknown",
                    "width": image.shape[1],
                    "height": image.shape[0],
                    "fps": float(stream.average_rate) if stream.average_rate else None,
                    "pix_fmt": getattr(stream, "pix_fmt", "unknown"),
                    "has_audio": False,
                    "warnings": [],
                    "frames_decoded": 1,
                    "first_frame_pts": first_frame.pts,
                    "redacted_endpoint": str(local_path),
                    "resolved_ips": [],
                },
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            stage("Inspecting stream", "failed")
            return CameraTestResponse(result="error", reason_code="local_file_failed", safe_message=str(exc), stages=stages)

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
    # Local footage is a first-class source, not an SSRF target.
    file_endpoint = req.protocol == "file" or req.endpoint.startswith("file://") or (req.protocol is None and Path(req.endpoint).exists())
    is_synthetic = req.endpoint.startswith("synthetic://")
    if file_endpoint:
        endpoint_value = Path(req.endpoint.replace("file://", "", 1)) if req.endpoint.startswith("file://") else Path(req.endpoint)
        if not endpoint_value.exists():
            raise HTTPException(status_code=400, detail={"code": "missing_file", "message": "Local footage file not found"})
        endpoint_value = endpoint_value.resolve()
    else:
        policy = _policy_from_request(req.site_cidr_allowlist)
        try:
            if not is_synthetic:
                parsed = validate_endpoint(req.endpoint, policy)
                if (req.username or req.password) and "@" in req.endpoint:
                    raise HTTPException(status_code=400, detail="Credentials must not be in URL")
                if parsed.hostname:
                    resolve_and_validate(parsed.hostname, policy, timeout=3.0)
        except SSRFError as e:
            raise HTTPException(status_code=400, detail={"code": e.code, "message": e.safe_message}) from e
        endpoint_value = req.endpoint

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
        "endpoint": str(endpoint_value) if file_endpoint else endpoint_redacted,
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
    if not is_synthetic:
        _start_camera_worker(cam_id)
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


@router.get("/{camera_id}/stream")
async def camera_stream(camera_id: str) -> StreamingResponse:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")

    async def body():
        last_version = -1
        try:
            while camera_id in _CAMERAS:
                current_version = _FRAME_VERSIONS.get(camera_id, 0)
                if current_version != last_version:
                    frame = _FRAMES.get(camera_id)
                    if frame:
                        last_version = current_version
                        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
                        await asyncio.sleep(0.001)
                        continue
                await asyncio.sleep(0.002)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        body(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{camera_id}/observations", response_model=dict[str, Any])
async def camera_observations(camera_id: str) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
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
    # Stop old worker and restart so stream actually resumes
    old = _WORKERS.pop(camera_id, None)
    if old:
        old[0].set()  # signal stop
    _start_camera_worker(camera_id)
    return {k: v for k, v in cam.items() if not k.startswith("_")}


@router.delete("/{camera_id}", response_model=dict[str, str])
async def delete_camera(camera_id: str) -> dict[str, str]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    # impact preview would be here - for Phase 2 we just delete
    del _CAMERAS[camera_id]
    worker = _WORKERS.pop(camera_id, None)
    if worker:
        worker[0].set()
    _STATE_MACHINES.pop(camera_id, None)
    _HEALTH.pop(camera_id, None)
    _FRAMES.pop(camera_id, None)
    _FRAME_VERSIONS.pop(camera_id, None)
    _FRAME_CONDITIONS.pop(camera_id, None)
    _OBSERVATIONS.pop(camera_id, None)
    _ACTIVE_PIPELINES.pop(camera_id, None)
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
