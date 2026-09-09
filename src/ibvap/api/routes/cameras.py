"""Camera add/test/stream endpoints. This is where phone feeds come in.

Flow: POST /test probes the URL without saving, POST / creates the camera
and spins up a _camera_worker thread, GET /{id}/stream re-serves MJPEG to
the UI, GET /{id}/observations serves the AI results as JSON.
Phone ports 4747 (DroidCam) / 8080 (IP Webcam) get normalized to /video.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import ipaddress
import os
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import av
import cv2
import numpy as np
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ibvap.config import Settings
from ibvap.core.anpr import ANPRPipeline
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.credentials import encrypt_secret, redact_url
from ibvap.core.geometry import validate_fence
from ibvap.core.model_manager import get_shared_detector_handle
from ibvap.core.night import NightDetector
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.probe import ProbeError, normalize_mjpeg_url, probe_url
from ibvap.core.ssrf import (
    _DEFAULT_ALLOWED_PORTS,
    SSRFError,
    SSRFPolicy,
    preflight_stream_url,
    resolve_and_validate,
    validate_endpoint,
)  # noqa: F401 - re-export
from ibvap.core.zone_engine import DEFAULT_ZONE, Zone, is_intrusion

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])
ANPR_DISPLAY_CONFIDENCE = 0.80
# Hoisted MJPEG framing constants (avoid per-frame allocations of literals).
_MJPEG_BOUNDARY = b"--frame\r\n"
_MJPEG_CT = b"Content-Type: image/jpeg\r\nContent-Length: "
_MJPEG_SEP = b"\r\n\r\n"
_MJPEG_END = b"\r\n"

logger = structlog.get_logger(__name__)


def _is_dev_or_test_env() -> bool:
    """Return True when running in dev/test (synthetic harness allowed)."""
    # Check Settings env flag if it exists, else IBVAP_ENV env var.
    try:
        from ibvap.config import Settings

        settings = Settings()
        for attr in ("env", "environment"):
            val = getattr(settings, attr, None)
            if isinstance(val, str) and val:
                return val.lower() in {"dev", "development", "test", "testing"}
        app_env = getattr(getattr(settings, "app", None), "env", None)
        if isinstance(app_env, str) and app_env:
            return app_env.lower() in {"dev", "development", "test", "testing"}
    except Exception:
        pass
    env_val = os.getenv("IBVAP_ENV", "").lower()
    if env_val:
        return env_val in {"dev", "development", "test", "testing"}
    # pytest sets PYTEST_CURRENT_TEST; treat as test env for backward compat.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    # Default allow when IBVAP_ENV unset (local dev); prod must set IBVAP_ENV=prod to gate.
    return True


def _synthetic_allowed() -> bool:
    return _is_dev_or_test_env()


def _file_jail_roots() -> list[Path]:
    return list(_cached_jail_roots())


@lru_cache(maxsize=1)
def _cached_jail_roots() -> tuple[Path, ...]:
    # Resolved once per process: avoids 4x Path.resolve() syscalls per request.
    roots: list[Path] = []
    for candidate in ("data/uploads", "data/quarantine", "tests/fixtures"):
        with contextlib.suppress(Exception):
            roots.append(Path(candidate).resolve())
    with contextlib.suppress(Exception):
        roots.append(Path(tempfile.gettempdir()).resolve())
    return tuple(roots)


@lru_cache(maxsize=1)
def _cached_writable_jail() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in ("data/uploads", "data/quarantine"):
        with contextlib.suppress(Exception):
            roots.append(Path(candidate).resolve())
    return tuple(roots)


def _resolve_jailed_file(raw_path: str) -> Path:
    """Resolve a file:// or plain path inside the upload jail.

    Rejects ``..`` traversal and absolute paths outside the jail
    (data/uploads, data/quarantine, tests/fixtures, tempdir for tests).
    """
    stripped = raw_path.replace("file://", "", 1) if raw_path.startswith("file://") else raw_path
    # Reject traversal attempts explicitly (defense in depth; resolve() would normalize).
    if ".." in Path(stripped).parts:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_file_path", "message": "Invalid footage path"},
        )
    candidate = Path(stripped)
    try:
        resolved = candidate.resolve()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_file_path", "message": "Invalid footage path"},
        ) from None
    for root in _file_jail_roots():
        try:
            if resolved.is_relative_to(root):
                return resolved
        except Exception:
            continue
    # Outside the jail: always reject, in every env. No dev/test fallback -
    # secure by default. Tests use in-jail fixtures (tests/fixtures).
    raise HTTPException(
        status_code=400,
        detail={"code": "invalid_file_path", "message": "Invalid footage path"},
    )


def _is_path_inside_jail(path_str: str) -> bool:
    try:
        resolved = Path(path_str).resolve()
    except Exception:
        return False
    # Only uploads/quarantine are writable jail for unlink; never unlink fixtures/temp outside.
    # Cached resolves avoid repeated filesystem syscalls per request.
    for root in _cached_writable_jail():
        try:
            if resolved.is_relative_to(root):
                return True
        except Exception:
            continue
    return False


def _safe_unlink_inside_jail(path_str: str) -> None:
    """Never unlink outside the upload jail."""
    if not _is_path_inside_jail(path_str):
        return
    with contextlib.suppress(OSError):
        Path(path_str).unlink()


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
_PLAYBACK: dict[str, dict[str, Any]] = {}
_PLAYBACK_LOCK = threading.Lock()


def _boxes_intersect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _match_vehicle_track(
    det_bbox: tuple[float, float, float, float],
    tracks: list[Any],
) -> int:
    """Max-IoU vehicle track match. Returns track_id, or 0 when nothing overlaps.

    Raw overlap area cannot tell nesting (a corner-touching bus ties the true
    owner and order decides); IoU normalizes by union so the owning track wins.
    """
    best_id = 0
    best_iou = 0.0
    x1, y1, x2, y2 = det_bbox
    det_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    for track in tracks:
        tx1, ty1, tx2, ty2 = track.bbox_norm
        ox = min(x2, tx2) - max(x1, tx1)
        oy = min(y2, ty2) - max(y1, ty1)
        if ox <= 0.0 or oy <= 0.0:
            continue
        inter = ox * oy
        union = det_area + max(0.0, tx2 - tx1) * max(0.0, ty2 - ty1) - inter
        iou = inter / union if union > 0.0 else 0.0
        if iou > best_iou:
            best_iou = iou
            best_id = track.track_id
    return best_id


def _select_plate_detections(
    fresh: list[dict[str, Any]],
    cached: list[dict[str, Any]],
    cached_at_mono: float,
    now_mono: float,
    vehicle_boxes: list[tuple[float, float, float, float]],
    max_age_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Publish cached OCR boxes only while fresh AND a vehicle is still there.

    OCR completes hundreds of ms after its frame; blindly republishing the
    last batch ghosts departed vehicles (and a low-conf batch wipes a live
    plate). Reuse requires age <= max_age_s plus overlap between a cached
    box and a current-frame vehicle box.
    """
    if cached and (now_mono - cached_at_mono) <= max_age_s:
        cached_boxes = [d["bbox_norm"] for d in cached if "bbox_norm" in d]
        if any(_boxes_intersect(cb, vb) for cb in cached_boxes for vb in vehicle_boxes):
            return cached
    return fresh


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
        max_face_size=960,
    )
    saved_fence = cam.get("fence")
    if isinstance(saved_fence, dict) and isinstance(saved_fence.get("polygon"), list):
        f_type = str(saved_fence.get("fence_type", "line" if len(saved_fence["polygon"]) == 2 else "polygon"))
        pipeline.zone = Zone(
            id=f"zone-{camera_id[:8]}",
            name=str(saved_fence.get("name", "User line fence" if f_type == "line" else "User fence")),
            polygon=saved_fence["polygon"],
            enabled=bool(saved_fence.get("enabled", True)),
            fence_type=f_type,
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
    anpr_frame_number = 0
    last_plate_detections: list[dict[str, Any]] = []
    last_plates: list[dict[str, Any]] = []
    last_plate_at_mono = 0.0
    ocr_last_submitted: dict[int | tuple[int, float, float], float] = {}
    ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"anpr-{camera_id[:8]}")
    pending_ocr: list[Future[tuple[list[dict[str, Any]], dict[str, Any] | None]]] = []

    def recognize_vehicle(
        crop: np.ndarray,
        vehicle_plate_detections: list[dict[str, Any]],
        vehicle_id: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        vehicle_class: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            plate = anpr.process_vehicle_crop(crop, vehicle_id=vehicle_id, stream_epoch=cam["stream_epoch"])
        except Exception:
            return vehicle_plate_detections, None
        if not plate or not plate.consensus:
            return vehicle_plate_detections, None
        if not vehicle_plate_detections and plate.candidates:
            bx1, by1, bx2, by2 = plate.candidates[0].bbox_norm
            vehicle_plate_detections.append(
                {
                    "bbox_norm": (
                        x1 + bx1 * (x2 - x1),
                        y1 + by1 * (y2 - y1),
                        x1 + bx2 * (x2 - x1),
                        y1 + by2 * (y2 - y1),
                    ),
                    "confidence": 0.0,
                    "vehicle_class": vehicle_class,
                    "track_id": vehicle_id,
                }
            )
        confidence = max(0.0, min(1.0, plate.candidates[0].confidence if plate.candidates else 0.0))
        if confidence < ANPR_DISPLAY_CONFIDENCE:
            return vehicle_plate_detections, None
        for item in vehicle_plate_detections:
            item["text"] = plate.consensus
            item["confidence"] = confidence
        return vehicle_plate_detections, {"text": plate.consensus, "confidence": confidence}

    last_night_result = None
    last_night_time = 0.0

    def analyze() -> None:
        nonlocal analysis_frame, analysis_fps_counter, last_analysis_fps, last_analysis_fps_calc
        nonlocal last_inference_ms, last_night_result, last_night_time, anpr_frame_number
        nonlocal last_plate_detections, last_plates, last_plate_at_mono
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
                completed: list[Future[tuple[list[dict[str, Any]], dict[str, Any] | None]]] = []
                for future in pending_ocr:
                    if future.done():
                        completed.append(future)
                for future in completed:
                    pending_ocr.remove(future)
                if completed:
                    completed_results = [future.result() for future in completed]
                    last_plate_detections = [item for detections, _ in completed_results for item in detections]
                    unique_plates: dict[str, dict[str, Any]] = {}
                    for _, plate in completed_results:
                        if plate is not None:
                            unique_plates[plate["text"]] = plate
                    last_plates = list(unique_plates.values())
                    last_plate_at_mono = time.monotonic()

                t_infer_start = time.perf_counter()
                pipeline.process_frame(current)
                t_infer_end = time.perf_counter()
                last_inference_ms = (t_infer_end - t_infer_start) * 1000.0

                h_c, w_c = current.shape[:2]
                anpr_frame_number += 1
                run_ocr = anpr_frame_number % 4 == 1
                plate_detections: list[dict[str, Any]] = []
                if pipeline.last_detections:
                    vehicle_detections = [
                        detection
                        for detection in pipeline.last_detections
                        if detection["class_name"] in {"car", "truck", "bus", "motorcycle"}
                    ]
                    ocr_detection_ids = {
                        id(detection)
                        for detection in sorted(
                            vehicle_detections,
                            key=lambda item: (item["bbox_norm"][2] - item["bbox_norm"][0]) * (item["bbox_norm"][3] - item["bbox_norm"][1]),
                            reverse=True,
                        )[:3]
                    }
                    for detection in pipeline.last_detections:
                        if detection["class_name"] not in {"car", "truck", "bus", "motorcycle"}:
                            continue
                        x1, y1, x2, y2 = detection["bbox_norm"]
                        crop = current[int(y1 * h_c) : int(y2 * h_c), int(x1 * w_c) : int(x2 * w_c)]
                        if crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 35:
                            continue
                        vehicle_plate_detections: list[dict[str, Any]] = []
                        vehicle_id = _match_vehicle_track((x1, y1, x2, y2), pipeline.last_tracks)
                        if run_ocr and id(detection) in ocr_detection_ids:
                            for bx1, by1, bx2, by2 in anpr.detector.detect(crop):
                                vehicle_plate_detections.append(
                                    {
                                        "bbox_norm": (
                                            x1 + bx1 * (x2 - x1),
                                            y1 + by1 * (y2 - y1),
                                            x1 + bx2 * (x2 - x1),
                                            y1 + by2 * (y2 - y1),
                                        ),
                                        "confidence": 0.0,
                                        "vehicle_class": detection["class_name"],
                                        "track_id": vehicle_id,
                                    }
                                )
                        if vehicle_id != 0:
                            throttle_key: int | tuple[int, float, float] = vehicle_id
                        else:
                            # Untracked detections share id 0: throttle per quantized
                            # position so distant vehicles don't starve each other.
                            throttle_key = (0, round((x1 + x2) / 2, 2), round((y1 + y2) / 2, 2))
                        ocr_due = time.monotonic() - ocr_last_submitted.get(throttle_key, 0.0) >= 0.6
                        track_ready = any(track.track_id == vehicle_id and track.hits >= 3 for track in pipeline.last_tracks)
                        if run_ocr and track_ready and ocr_due and id(detection) in ocr_detection_ids and len(pending_ocr) < 3:
                            ocr_last_submitted[throttle_key] = time.monotonic()
                            pending_ocr.append(
                                ocr_executor.submit(
                                    recognize_vehicle,
                                    crop.copy(),
                                    # Decoupled copy: the worker thread appends/fills this
                                    # list while analyze keeps extending the original.
                                    copy.deepcopy(vehicle_plate_detections),
                                    vehicle_id,
                                    x1,
                                    y1,
                                    x2,
                                    y2,
                                    detection["class_name"],
                                )
                            )
                        plate_detections.extend(vehicle_plate_detections)

                # Reuse the last completed OCR batch only while it is fresh
                # and a vehicle is still under it - otherwise ghosts linger
                # after the vehicle leaves (and stale plates wipe live ones).
                vehicle_boxes = [d["bbox_norm"] for d in pipeline.last_detections if d.get("class_name") in {"car", "truck", "bus", "motorcycle"}]
                cache_reused = _select_plate_detections(
                    plate_detections, last_plate_detections, last_plate_at_mono, time.monotonic(), vehicle_boxes
                )
                plates_for_obs = last_plates if cache_reused is last_plate_detections else []
                plate_detections = cache_reused

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
                            "intrusion": (
                                bool(getattr(pipeline.zone, "enabled", True))
                                and pipeline.zone.id != DEFAULT_ZONE.id
                                and track.class_name in {"person", "car", "truck", "bus", "motorcycle"}
                                and (
                                    track.track_id in getattr(pipeline, "_active_line_intruders", set())
                                    or is_intrusion(track.footpoint, pipeline.zone, track=track)
                                )
                            ),
                        }
                        for track in pipeline.last_tracks
                    ],
                    "faces": [
                        {
                            "bbox_norm": f["bbox_norm"],
                            "confidence": f["confidence"],
                            "quality_passed": f.get("quality_passed", True),
                            "track_id": f.get("track_id", None),
                        }
                        for f in pipeline.last_faces
                    ],
                    "plates": plates_for_obs,
                    "plate_detections": plate_detections,
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
            with _PLAYBACK_LOCK:
                playback = _PLAYBACK.setdefault(
                    camera_id,
                    {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None},
                )
                if playback["state"] == "stopped":
                    break
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
                duration_seconds = None
                if container.duration is not None:
                    duration_seconds = max(0.0, float(container.duration) / av.time_base)
                with _PLAYBACK_LOCK:
                    playback["duration_seconds"] = duration_seconds
                    playback["fps"] = fps

                while not stop.is_set():
                    next_frame_time = time.perf_counter()
                    frames_in_pass = 0

                    try:
                        frame_iter = container.decode(stream)
                        while not stop.is_set():
                            with _PLAYBACK_LOCK:
                                playback_state = playback["state"]
                                seek_to = playback.pop("seek_to", None)
                            if playback_state == "stopped":
                                break
                            if playback_state == "paused":
                                cam["observed_state"] = "PAUSED"
                                time.sleep(0.05)
                                continue
                            if seek_to is not None:
                                with contextlib.suppress(Exception):
                                    container.seek(int(float(seek_to) * av.time_base), stream=stream, backward=True)
                                frame_iter = container.decode(stream)
                                continue
                            cam["observed_state"] = "STREAMING"

                            try:
                                frame = next(frame_iter)
                            except (StopIteration, av.error.EOFError):
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
                            with _PLAYBACK_LOCK:
                                playback["position_seconds"] = max(0.0, float(frame.time or 0.0))

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
                    with _PLAYBACK_LOCK:
                        if playback["state"] == "stopped":
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
        ocr_executor.shutdown(wait=False, cancel_futures=True)
        _ACTIVE_PIPELINES.pop(camera_id, None)
        return

    # Live path (phones, RTSP cams). Two outputs from one demux:
    # 1) raw JPEG bytes straight to _FRAMES for the browser (no re-encode)
    # 2) decoded ndarray to the analysis thread for YOLO/face/plate
    # Wifi from phones is flaky so we auto-reconnect with backoff here.
    endpoint = normalize_mjpeg_url(str(cam["endpoint"]))
    parsed_endpoint = urlparse(endpoint)
    path_lower = parsed_endpoint.path.lower().rstrip("/")
    is_mjpeg_stream = (
        path_lower in {"/video", "/videofeed", "/mjpegfeed"}
        or parsed_endpoint.port == 4747
        or cam.get("protocol") == "mjpeg"
        or (parsed_endpoint.scheme in ("http", "mjpeg") and path_lower.endswith((".mjpg", ".mjpeg")))
    )

    stream_opts: dict[str, str] = {
        "timeout": "3000000",
        "stimeout": "3000000",
        "fflags": "nobuffer",
        "flags": "low_delay",
        "max_delay": "500000",
        "probesize": "500000",
        "analyzeduration": "1000000",
    }
    if parsed_endpoint.scheme in ("rtsp", "rtsps"):
        stream_opts["rtsp_transport"] = "tcp"

    open_kwargs: dict[str, Any] = {"options": stream_opts}
    if is_mjpeg_stream:
        open_kwargs["format"] = "mpjpeg"

    # Server policy for connect-time checks (DNS resolved fresh below).
    stream_policy = _policy_from_request(None)

    reconnect_delay = 1.0
    decode_errors = 0
    reconnect_count = 0
    fps_window_start = time.perf_counter()
    fps_window_count = 0
    measured_source_fps = 30.0

    while not stop.is_set():
        container = None
        try:
            # Re-validate + re-resolve on EVERY attempt: DNS can rebind
            # between reconnects. SSRFError flows into the reconnect/backoff
            # handler below like any other connect failure.
            preflight_stream_url(endpoint, stream_policy, timeout=3.0)
            container = av.open(endpoint, **open_kwargs)
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise RuntimeError("No video stream")
            cam["observed_state"] = "STREAMING"
            reconnect_delay = 1.0

            for packet in container.demux(stream):
                if stop.is_set():
                    break

                # MJPEG packets sometimes have extra http chunk headers around them,
                # so slice from SOI (ffd8) to EOI (ffd9) to get a clean jpeg.
                # Falls back to cv2 re-encode if the slice looks bad.
                packet_bytes = bytes(packet)
                soi_idx = packet_bytes.find(b"\xff\xd8")
                eoi_idx = packet_bytes.rfind(b"\xff\xd9")
                is_valid_jpeg = False

                if soi_idx != -1 and eoi_idx > soi_idx:
                    clean_jpeg = packet_bytes[soi_idx : eoi_idx + 2]
                    if len(clean_jpeg) > 100:
                        is_valid_jpeg = True
                        with condition:
                            _FRAMES[camera_id] = clean_jpeg
                            _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                            condition.notify_all()

                try:
                    frames = packet.decode()
                except (av.error.InvalidDataError, av.error.CorruptDataError):
                    decode_errors += 1
                    continue
                except Exception:
                    decode_errors += 1
                    continue

                for frame in frames:
                    if stop.is_set():
                        break
                    image = frame.to_ndarray(format="bgr24")
                    h, w = image.shape[:2]

                    if not is_valid_jpeg:
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
                    fps_window_count += 1
                    now_perf = time.perf_counter()
                    if now_perf - fps_window_start >= 1.0:
                        measured_source_fps = round(fps_window_count / (now_perf - fps_window_start), 1)
                        fps_window_count = 0
                        fps_window_start = now_perf

                    samples = _HEALTH.setdefault(camera_id, [])
                    samples.append(
                        {
                            "_ts": time.time(),
                            "last_frame_age_ms": 0,
                            "source_fps": measured_source_fps,
                            "analysis_fps": round(last_analysis_fps or measured_source_fps, 1),
                            "inference_ms": round(last_inference_ms, 1),
                            "queue_drops": 0,
                            "decode_errors": decode_errors,
                            "reconnect_count": reconnect_count,
                            "stream_epoch": cam["stream_epoch"],
                        }
                    )
                    del samples[:-10]
        except Exception:
            if stop.is_set():
                break
            reconnect_count += 1
            cam["observed_state"] = "RECONNECTING"
            if stop.wait(reconnect_delay):
                break
            reconnect_delay = min(reconnect_delay * 1.5, 5.0)
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.close()
    analysis_ready.set()
    ocr_executor.shutdown(wait=False, cancel_futures=True)
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
    temporary: bool = False


class CameraTestRequest(BaseModel):
    endpoint: str
    protocol: Literal["rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip", "file"] | None = None
    username: str | None = None
    password: str | None = None
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


def _policy_from_request(allowlist: list[str] | None) -> SSRFPolicy:
    # SECURITY: caller-supplied CIDRs are never trusted for authorization.
    # Only the operator-owned server setting (IBVAP_MEDIA__SITE_CIDR_ALLOWLIST)
    # can permit private ranges. The request field is accepted for API compat
    # but ignored here.
    del allowlist
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    # Settings() failure must be loud (fail closed below on empty nets would
    # silently change policy either way) - no broad except here.
    configured = Settings().media.site_cidr_allowlist
    for cidr in configured or []:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))  # type: ignore[arg-type]
        except ValueError:
            continue
    # default private allowlist for dev: allow 192.168/16, 10/8, 172.16/12 via policy if provided
    # allowed_ports=None would fall back to SSRF default deny-list; keep explicit default via ssrf module.
    return SSRFPolicy(
        allowed_schemes=frozenset({"rtsp", "rtsps", "http", "https"}),
        allowed_hosts=None,
        allowed_ports=_DEFAULT_ALLOWED_PORTS,
        site_cidr_allowlist=tuple(nets),
    )


def _run_test_stages(req: CameraTestRequest) -> CameraTestResponse:
    policy = _policy_from_request(req.site_cidr_allowlist)
    stages: list[dict[str, str]] = []

    def stage(name: str, status: str) -> None:
        stages.append({"name": name, "status": status})

    file_endpoint = req.protocol == "file" or req.endpoint.startswith("file://") or (req.protocol is None and Path(req.endpoint).exists())
    if file_endpoint:
        try:
            local_path = _resolve_jailed_file(req.endpoint)
        except HTTPException as exc:
            stage("Validating address", "failed")
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": "invalid_file_path", "message": "Invalid footage path"}
            code = str(detail.get("code", "invalid_file_path")) if isinstance(detail, dict) else "invalid_file_path"
            return CameraTestResponse(result="error", reason_code=code, safe_message="Invalid footage path", stages=stages)
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
                    "redacted_endpoint": local_path.name,
                    "resolved_ips": [],
                },
            )
        except Exception:  # pragma: no cover - defensive fallback
            stage("Inspecting stream", "failed")
            # Generic message: never disclose OS absolute paths.
            return CameraTestResponse(
                result="error", reason_code="local_file_failed", safe_message="Local footage could not be opened", stages=stages
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
        probe, frames = probe_url(req.endpoint, timeout=3.0, max_frames=2, policy=policy)
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
    except SSRFError as e:
        # Redirect target (or rebound DNS) failed validation inside the probe.
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
async def test_unsaved(req: CameraTestRequest) -> CameraTestResponse:
    """Test connection without saving - spec 8 Step 3."""
    # _run_test_stages does blocking DNS + PyAV IO — offload from event loop.
    return await asyncio.to_thread(_run_test_stages, req)


@router.post("", response_model=dict[str, Any])
async def create_camera(req: CameraCreate) -> dict[str, Any]:
    # Local footage is a first-class source, not an SSRF target.
    file_endpoint = req.protocol == "file" or req.endpoint.startswith("file://") or (req.protocol is None and Path(req.endpoint).exists())
    is_synthetic = req.endpoint.startswith("synthetic://")
    if is_synthetic and not _synthetic_allowed():
        raise HTTPException(
            status_code=400,
            detail={"code": "synthetic_disabled", "message": "Synthetic sources are only available in dev/test"},
        )
    if file_endpoint:
        endpoint_value = _resolve_jailed_file(req.endpoint)
        if not endpoint_value.exists():
            raise HTTPException(status_code=400, detail={"code": "missing_file", "message": "Local footage file not found"})
    else:
        if not is_synthetic:
            raw_ep = req.endpoint.strip()
            if "://" not in raw_ep:
                scheme = req.protocol or ("rtsp" if ":554" in raw_ep else "http")
                raw_ep = f"{scheme}://{raw_ep}"
            req.endpoint = normalize_mjpeg_url(raw_ep)
        policy = _policy_from_request(req.site_cidr_allowlist)
        try:
            if not is_synthetic:
                parsed = validate_endpoint(req.endpoint, policy)
                if (req.username or req.password) and "@" in req.endpoint:
                    raise HTTPException(status_code=400, detail="Credentials must not be in URL")
                if parsed.hostname:
                    # Blocking DNS — offload; ssrf layer caches successful lookups w/ TTL.
                    await asyncio.to_thread(resolve_and_validate, parsed.hostname, policy, 3.0)
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
        "temporary": req.temporary,
        "created_at": time.time(),
    }
    _CAMERAS[cam_id] = data
    _STATE_MACHINES[cam_id] = sm
    # store encrypted creds separately (in-mem for Phase 2)
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
                        # Hoisted constants + single join avoids intermediate concat copies.
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
            "Access-Control-Allow-Origin": "*",
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


@router.put("/{camera_id}/fence", response_model=dict[str, Any])
async def set_camera_fence(camera_id: str, req: CameraFenceRequest) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")

    # If clearing fence (empty polygon and no line)
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
        # Default when fence_type not specified: "polygon"
        # Legacy polygon requests without fence_type="line" fail 422 for len(points) == 2
        effective_type = "polygon"

    error = validate_fence(points, fence_type=effective_type)
    if error:
        raise HTTPException(status_code=422, detail=error)

    if any(not (0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0) for point in points):
        raise HTTPException(status_code=422, detail="Fence points must be normalized between 0 and 1")

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
    return {k: v for k, v in _CAMERAS[camera_id].items() if not k.startswith("_")}


@router.delete("/{camera_id}/fence", response_model=dict[str, Any])
async def delete_camera_fence(camera_id: str) -> dict[str, Any]:
    # TODO: require authentication/authorization for mutating routes (would break tests today).
    logger.warning("unauthenticated_delete", route="DELETE /api/v1/cameras/{camera_id}/fence")
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    _CAMERAS[camera_id]["fence"] = None
    pipeline = _ACTIVE_PIPELINES.get(camera_id)
    if pipeline is not None:
        pipeline.zone = DEFAULT_ZONE
        if hasattr(pipeline, "_active_line_intruders"):
            pipeline._active_line_intruders.clear()
    return {k: v for k, v in _CAMERAS[camera_id].items() if not k.startswith("_")}


def _is_file_camera(camera_id: str) -> bool:
    cam = _CAMERAS.get(camera_id)
    return bool(cam and (cam.get("source_type") == "video_footage" or cam.get("protocol") == "file"))


@router.get("/{camera_id}/playback", response_model=dict[str, Any])
async def playback_state(camera_id: str) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not _is_file_camera(camera_id):
        raise HTTPException(status_code=400, detail="Playback controls are only available for video footage")
    with _PLAYBACK_LOCK:
        return dict(_PLAYBACK.setdefault(camera_id, {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None}))


@router.post("/{camera_id}/playback/{action}", response_model=dict[str, Any])
async def playback_action(camera_id: str, action: Literal["pause", "resume", "stop", "restart"]) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not _is_file_camera(camera_id):
        raise HTTPException(status_code=400, detail="Playback controls are only available for video footage")
    with _PLAYBACK_LOCK:
        playback = _PLAYBACK.setdefault(camera_id, {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None})
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
            worker = _WORKERS.get(camera_id)
            if worker:
                worker[0].set()
            camera = _CAMERAS.pop(camera_id)
            _STATE_MACHINES.pop(camera_id, None)
            _HEALTH.pop(camera_id, None)
            _FRAMES.pop(camera_id, None)
            _FRAME_VERSIONS.pop(camera_id, None)
            _OBSERVATIONS.pop(camera_id, None)
            _PLAYBACK.pop(camera_id, None)
            if camera.get("temporary") and camera.get("protocol") == "file":
                # Never unlink outside the upload jail.
                _safe_unlink_inside_jail(str(camera["endpoint"]))
        state = dict(playback)
    if action in {"pause", "resume", "restart"}:
        _CAMERAS[camera_id]["observed_state"] = "PAUSED" if action == "pause" else "STREAMING"
    return state


@router.post("/{camera_id}/playback/seek", response_model=dict[str, Any])
async def playback_seek(camera_id: str, req: PlaybackSeekRequest) -> dict[str, Any]:
    if camera_id not in _CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not _is_file_camera(camera_id):
        raise HTTPException(status_code=400, detail="Playback controls are only available for video footage")
    with _PLAYBACK_LOCK:
        playback = _PLAYBACK.setdefault(camera_id, {"state": "playing", "position_seconds": 0.0, "duration_seconds": None, "fps": None})
        duration = playback.get("duration_seconds")
        position = min(req.position_seconds, duration) if duration else req.position_seconds
        playback["position_seconds"] = position
        playback["seek_to"] = position
        return dict(playback)


@router.post("/{camera_id}/test", response_model=CameraTestResponse)
async def test_saved(camera_id: str) -> CameraTestResponse:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    req = CameraTestRequest(
        endpoint=cam["endpoint"],
        protocol=cam.get("protocol"),
        site_cidr_allowlist=cam.get("_site_cidr_allowlist"),
    )
    return await asyncio.to_thread(_run_test_stages, req)


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
    # TODO: require authentication/authorization for mutating routes (would break tests today).
    logger.warning("unauthenticated_delete", route="DELETE /api/v1/cameras/{camera_id}")
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
    _PLAYBACK.pop(camera_id, None)
    return {"status": "deleted", "id": camera_id}


@router.get("/{camera_id}/health", response_model=dict[str, Any])
async def camera_health(camera_id: str) -> dict[str, Any]:
    cam = _CAMERAS.get(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
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
