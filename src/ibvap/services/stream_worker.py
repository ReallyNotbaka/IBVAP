"""Stream worker orchestration and lifecycle management for IBVAP cameras.

Manages background capture threads, MJPEG streaming subscribers, frame versioning,
decoupled AI pipeline execution, native file playback pacing, and camera health metrics.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import ipaddress
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import av
import cv2
import numpy as np
import structlog

from ibvap.config import Settings
from ibvap.core.anpr import ANPRPipeline, get_sightings_store
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.credentials import build_authenticated_url, decrypt_secret
from ibvap.core.jail import (
    _clean_file_path,
    _file_jail_roots,
)
from ibvap.core.model_manager import get_shared_detector_handle
from ibvap.core.night import NightDetector
from ibvap.core.ocr_worker import (
    ANPR_DISPLAY_CONFIDENCE,
    _match_vehicle_track,
    _select_plate_detections,
)
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.probe import normalize_mjpeg_url
from ibvap.core.ssrf import (
    _DEFAULT_ALLOWED_PORTS,
    SSRFError,
    SSRFPolicy,
    pin_stream_url,
)
from ibvap.core.watchlist import get_watchlist_store
from ibvap.core.zone_engine import DEFAULT_ZONE, Zone

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.windll.winmm.timeBeginPeriod(1)

logger = structlog.get_logger(__name__)

# Hoisted MJPEG framing constants (avoid per-frame allocations of literals).
_MJPEG_BOUNDARY = b"--frame\r\n"
_MJPEG_CT = b"Content-Type: image/jpeg\r\nContent-Length: "
_MJPEG_SEP = b"\r\n\r\n"
_MJPEG_END = b"\r\n"

# In-memory store for Phase 2 demo (PG persistence via migrations; runtime wired in Phase 3)
_CAMERAS: dict[str, dict[str, Any]] = {}
_STATE_MACHINES: dict[str, CameraStateMachine] = {}
_HEALTH: dict[str, list[dict[str, Any]]] = {}
_WORKERS: dict[str, tuple[threading.Event, threading.Thread]] = {}
_WORKERS_LOCK = threading.Lock()
_STOPPING_WORKERS: dict[str, list[threading.Thread]] = {}
_FRAMES: dict[str, bytes] = {}
_FRAME_VERSIONS: dict[str, int] = {}
_FRAME_CONDITIONS: dict[str, threading.Condition] = {}
_STREAM_CLIENT_COUNT: dict[str, int] = {}
_STREAM_SUBSCRIBERS: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}
_STREAM_SUBSCRIBERS_LOCK = threading.Lock()

_OBSERVATIONS: dict[str, dict[str, Any]] = {}
_ACTIVE_PIPELINES: dict[str, MiniPipeline] = {}
_PLAYBACK: dict[str, dict[str, Any]] = {}
_PLAYBACK_LOCK = threading.Lock()


class CameraStreamContext:
    """Unified per-camera operational context encapsulating pipeline, frames, and health."""

    def __init__(
        self,
        camera_id: str,
        camera_data: dict[str, Any],
        state_machine: CameraStateMachine,
        pipeline: MiniPipeline | None = None,
        latest_frame: bytes | None = None,
        frame_version: int = 0,
        condition: threading.Condition | None = None,
        observations: dict[str, Any] | None = None,
        health: list[dict[str, Any]] | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.camera_data = camera_data
        self.state_machine = state_machine
        self.pipeline = pipeline
        self.latest_frame = latest_frame
        self.frame_version = frame_version
        self.condition = condition or threading.Condition()
        self.observations = observations or {}
        self.health = health or []


def get_stream_context(camera_id: str) -> CameraStreamContext | None:
    """Retrieve encapsulated operational context for a given camera."""
    cam = _CAMERAS.get(camera_id)
    if not cam:
        return None
    sm = _STATE_MACHINES.get(camera_id) or CameraStateMachine(camera_id=camera_id)
    return CameraStreamContext(
        camera_id=camera_id,
        camera_data=cam,
        state_machine=sm,
        pipeline=_ACTIVE_PIPELINES.get(camera_id),
        latest_frame=_FRAMES.get(camera_id),
        frame_version=_FRAME_VERSIONS.get(camera_id, 0),
        condition=_FRAME_CONDITIONS.setdefault(camera_id, threading.Condition()),
        observations=_OBSERVATIONS.get(camera_id, {}),
        health=_HEALTH.get(camera_id, []),
    )


def _policy_from_request(allowlist: list[str] | None) -> SSRFPolicy:
    # Task 3 override semantics: a non-None per-request allowlist REPLACES the
    # global settings (per-site isolation); None means global. An explicitly
    # passed list that parses to empty stays empty (deny private, fail-closed).
    configured = allowlist if allowlist is not None else Settings().media.site_cidr_allowlist
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in configured or []:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return SSRFPolicy(
        allowed_schemes=frozenset({"rtsp", "rtsps", "http", "https"}),
        allowed_hosts=None,
        allowed_ports=_DEFAULT_ALLOWED_PORTS,
        site_cidr_allowlist=tuple(nets),
    )


def _resync_epoch_if_bumped(
    cam_epoch: int,
    pipeline: MiniPipeline,
    *,
    track_plates: dict,
    ocr_last_submitted: dict,
    pending_ocr: list,
    plate_cache: dict[str, Any],
) -> bool:
    """Resync pipeline + worker OCR state to a bumped stream epoch.

    Returns True when a bump was handled. On bump: ``pipeline.reset_epoch``
    clears alert/track latches, worker-side plate/throttle caches are purged,
    and in-flight old-epoch OCR futures are cancelled (callers must tolerate
    ``CancelledError`` at ``Future.result()``) so a dead vehicle's votes can
    never decide a new vehicle's plate.
    """
    if cam_epoch == pipeline.stream_epoch:
        return False
    pipeline.reset_epoch(cam_epoch)
    track_plates.clear()
    ocr_last_submitted.clear()
    for future in pending_ocr:
        with contextlib.suppress(Exception):
            future.cancel()
    pending_ocr.clear()
    plate_cache["detections"] = []
    plate_cache["plates"] = []
    plate_cache["at_mono"] = 0.0
    return True


def _drain_ocr_futures(
    pending_ocr: list,
    timeout: float = 5.0,
    now: float | None = None,
) -> tuple[list, int]:
    """Non-blocking drain of pending OCR futures (hot path must not stall).

    Per iteration: done futures resolve in submission order (CancelledError /
    other -> dropped); not-done futures older than ``timeout`` (by per-future
    submit stamp) are cancelled, counted, and dropped; young-pending futures
    are RETAINED for a later iteration. Never blocks: no ``wait()``. Retaining
    young-pending means the list is not always emptied — the len<3 submit cap
    still bounds it, and wedged entries cannot clog it past ``timeout``.
    ``now`` is injectable for tests. Returns (results, timeouts).
    """
    results: list = []
    timeouts = 0
    if not pending_ocr:
        return results, timeouts
    now_mono = time.monotonic() if now is None else now
    keep: list = []
    for future in list(pending_ocr):
        if future.done():
            try:
                results.append(future.result())
            except Exception:
                continue
        else:
            submitted = getattr(future, "_ocr_submitted_mono", None)
            age = (now_mono - submitted) if submitted is not None else 0.0
            if age >= timeout:
                with contextlib.suppress(Exception):
                    future.cancel()
                timeouts += 1
            else:
                keep.append(future)
    pending_ocr[:] = keep
    return results, timeouts


def _notify_stream_subscribers(camera_id: str) -> None:
    with _STREAM_SUBSCRIBERS_LOCK:
        subs = list(_STREAM_SUBSCRIBERS.get(camera_id, set()))
    if not subs:
        return
    dead: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
    for loop, event in subs:
        if loop.is_closed():
            dead.append((loop, event))
            continue
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:
            dead.append((loop, event))
    if dead:
        with _STREAM_SUBSCRIBERS_LOCK:
            active_set = _STREAM_SUBSCRIBERS.get(camera_id)
            if active_set is not None:
                for item in dead:
                    active_set.discard(item)
                _STREAM_CLIENT_COUNT[camera_id] = len(active_set)
                if not active_set:
                    _STREAM_SUBSCRIBERS.pop(camera_id, None)


def _connect_endpoint(cam: dict[str, Any]) -> str:
    endpoint = str(cam["endpoint"])
    enc = cam.get("_enc") or {}
    if not enc.get("username") and not enc.get("password"):
        return endpoint
    try:
        user = decrypt_secret(enc["username"]) if enc.get("username") else None
        pw = decrypt_secret(enc.get("password")) if enc.get("password") else None
    except Exception as e:
        logger.warning("camera_credential_unavailable", camera_id=cam.get("id"), error=str(e)[:120])
        return endpoint
    return build_authenticated_url(endpoint, user, pw)


def _camera_worker(camera_id: str, stop: threading.Event) -> None:
    cam = _CAMERAS[camera_id]
    endpoint = str(cam["endpoint"])
    is_file_source = False
    try:
        if cam.get("source_type") == "video_footage" or cam.get("protocol") == "file":
            is_file_source = True
        else:
            p = Path(endpoint.replace("file://", "", 1)) if endpoint.startswith("file://") else Path(endpoint)
            if p.exists() and p.suffix.lower() in {".mp4", ".avi", ".mkv", ".mov", ".webm"}:
                is_file_source = True
    except Exception:
        is_file_source = False

    detector_handle = get_shared_detector_handle()
    pipeline = MiniPipeline(
        camera_id=camera_id,
        stream_epoch=cam["stream_epoch"],
        detector_handle=detector_handle,
        enable_face=True,
        face_stride=2,
        sample_stride=1,
        max_face_size=960,
        skip_face_without_person=True,
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
    # Worker-side OCR caches, epoch-scoped (see _resync_epoch_if_bumped).
    plate_cache: dict[str, Any] = {"detections": [], "plates": [], "at_mono": 0.0}
    ocr_last_submitted: dict[int | tuple[int, float, float], float] = {}
    ocr_timeouts = 0
    # Single-slot analysis handoff drops: frames overwritten before analyze()
    # consumed them. Exposed as queue_drops in health samples (TileHealth).
    analysis_overwrites = 0
    ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"anpr-{camera_id[:8]}")
    pending_ocr: list[Future[tuple[list[dict[str, Any]], dict[str, Any] | None]]] = []
    track_plates: dict[int, str] = {}

    def recognize_vehicle(
        crop: np.ndarray,
        vehicle_plate_detections: list[dict[str, Any]],
        vehicle_id: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        vehicle_class: str,
        plate_boxes: list[tuple[float, float, float, float]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            plate = anpr.process_vehicle_crop(
                crop,
                vehicle_id=vehicle_id,
                stream_epoch=cam["stream_epoch"],
                plate_boxes=plate_boxes,
            )
        except Exception:
            return [], None
        if not plate:
            return [], None
        confidence = max(0.0, min(1.0, plate.candidates[0].confidence if plate.candidates else 0.0))
        display_text = plate.consensus or (plate.plate_text if confidence >= ANPR_DISPLAY_CONFIDENCE else None)
        if not display_text or confidence < ANPR_DISPLAY_CONFIDENCE:
            return [], None
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
                    "confidence": confidence,
                    "vehicle_class": vehicle_class,
                    "track_id": vehicle_id,
                    "text": display_text,
                }
            )
        for item in vehicle_plate_detections:
            item["text"] = display_text
            item["confidence"] = confidence
        return vehicle_plate_detections, {"text": display_text, "confidence": confidence, "track_id": vehicle_id}

    last_night_result = None
    last_night_time = 0.0

    def analyze() -> None:
        nonlocal analysis_frame, analysis_fps_counter, last_analysis_fps, last_analysis_fps_calc
        nonlocal last_inference_ms, last_night_result, last_night_time, anpr_frame_number
        nonlocal ocr_timeouts
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
                # Task 3 fix R1: epoch poll FIRST — a bumped first new-epoch
                # frame must not run OCR-drain/process_frame/submit with stale
                # latches, else old-epoch votes apply then get discarded.
                _resync_epoch_if_bumped(
                    cam.get("stream_epoch", 0),
                    pipeline,
                    track_plates=track_plates,
                    ocr_last_submitted=ocr_last_submitted,
                    pending_ocr=pending_ocr,
                    plate_cache=plate_cache,
                )

                # Non-blocking drain: done resolve, wedged-by-age reaped+counted,
                # young-pending retained. Never stalls analyze() on OCR latency.
                completed_results, wedged = _drain_ocr_futures(pending_ocr, timeout=5.0)
                ocr_timeouts += wedged
                if completed_results:
                    plate_cache["detections"] = [item for detections, _ in completed_results for item in detections]
                    unique_plates: dict[str, dict[str, Any]] = {}
                    wl_store = get_watchlist_store()
                    sightings_store = get_sightings_store()
                    for _, plate in completed_results:
                        if plate is not None:
                            tid = plate.get("track_id")
                            plate_str = plate.get("text")
                            conf = float(plate.get("confidence", 0.90))
                            if tid and plate_str:
                                track_plates[tid] = plate_str
                                v_track = pipeline.tracker.tracks.get(tid)
                                v_class = getattr(v_track, "class_name", "car") if v_track else "car"
                                bbox = getattr(v_track, "bbox_norm", None) if v_track else None
                                sightings_store.record_sighting(
                                    camera_id=camera_id,
                                    plate_text=plate_str,
                                    confidence=conf,
                                    vehicle_class=v_class,
                                    bbox_norm=bbox,
                                )

                                match = wl_store.match_plate(plate_str)
                                if match is not None:
                                    if v_track is not None:
                                        v_track.identity = {
                                            "name": match.name,
                                            "score": match.score,
                                            "threat_level": match.threat_level.value,
                                            "tier": match.tier,
                                            "entry_id": match.entry_id,
                                            "target_type": "plate",
                                            "plate_number": plate_str,
                                        }
                                        v_track.identity_locked = True
                                    wl_store.record_sighting(match.entry_id, time.time())
                            if plate_str:
                                unique_plates[plate_str] = plate
                    plate_cache["plates"] = list(unique_plates.values())
                    plate_cache["at_mono"] = time.monotonic()

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
                        detection for detection in pipeline.last_detections if detection["class_name"] in {"car", "truck", "bus", "motorcycle"}
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
                        crop_plate_boxes: list[tuple[float, float, float, float]] = []
                        if run_ocr and id(detection) in ocr_detection_ids:
                            crop_plate_boxes = anpr.detector.detect(crop)
                            # Task 3: no blind full-vehicle fallback. OCRing bumper/
                            # grille texture hallucinates plates; empty boxes means
                            # skip OCR for this vehicle this round.
                            for bx1, by1, bx2, by2 in crop_plate_boxes:
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
                                        "text": track_plates.get(vehicle_id),
                                    }
                                )
                        if vehicle_id != 0:
                            throttle_key: int | tuple[int, float, float] = vehicle_id
                        else:
                            throttle_key = (0, round((x1 + x2) / 2, 2), round((y1 + y2) / 2, 2))
                        ocr_due = time.monotonic() - ocr_last_submitted.get(throttle_key, 0.0) >= 0.6
                        track_ready = any(track.track_id == vehicle_id and track.hits >= 3 for track in pipeline.last_tracks)
                        if run_ocr and track_ready and ocr_due and id(detection) in ocr_detection_ids and len(pending_ocr) < 3 and crop_plate_boxes:
                            ocr_last_submitted[throttle_key] = time.monotonic()
                            ocr_future = ocr_executor.submit(
                                recognize_vehicle,
                                crop.copy(),
                                copy.deepcopy(vehicle_plate_detections),
                                vehicle_id,
                                x1,
                                y1,
                                x2,
                                y2,
                                detection["class_name"],
                                list(crop_plate_boxes),
                            )
                            # Per-future submit stamp for the age-based reaper in
                            # _drain_ocr_futures (attribute dies with the future;
                            # missing stamp defaults to age 0 = never reap).
                            ocr_future._ocr_submitted_mono = time.monotonic()  # type: ignore[attr-defined]
                            pending_ocr.append(ocr_future)
                        if vehicle_plate_detections:
                            plate_detections.extend([d for d in vehicle_plate_detections if d.get("text")])

                vehicle_boxes = [d["bbox_norm"] for d in pipeline.last_detections if d.get("class_name") in {"car", "truck", "bus", "motorcycle"}]
                cache_reused = _select_plate_detections(plate_detections, plate_cache["detections"], plate_cache["at_mono"], time.monotonic(), vehicle_boxes)
                plate_detections = [d for d in cache_reused if d.get("text")]
                for d in plate_detections:
                    tid = d.get("track_id")
                    if tid and tid in track_plates and not d.get("text"):
                        d["text"] = track_plates[tid]

                # Prune dead vehicle tracks and bounded OCR throttle state
                active_tids = {t.track_id for t in pipeline.tracker.tracks.values()}
                anpr.evict_dead_tracks(active_track_ids=active_tids, stream_epoch=cam.get("stream_epoch", 0))
                for tid in list(track_plates):
                    if tid not in active_tids:
                        track_plates.pop(tid, None)

                # Persist plates for active vehicle tracks across frames
                active_plates = [p for p in plate_cache["plates"] if p.get("track_id") in active_tids or not p.get("track_id")]
                plates_for_obs = [{"text": text, "confidence": 0.90, "track_id": tid} for tid, text in track_plates.items()] or (
                    active_plates if active_plates else plate_cache["plates"]
                )

                now_m = time.monotonic()
                stale_ocr = [
                    k
                    for k, ts in ocr_last_submitted.items()
                    if (isinstance(k, int) and k not in active_tids and (now_m - ts) > 5.0) or (not isinstance(k, int) and (now_m - ts) > 5.0)
                ]
                for k in stale_ocr:
                    ocr_last_submitted.pop(k, None)

                # Safeguard max capacity on ocr_last_submitted (LRU)
                if len(ocr_last_submitted) > 512:
                    oldest_ocr = sorted(ocr_last_submitted.items(), key=lambda item: item[1])[: len(ocr_last_submitted) - 512]
                    for k, _ in oldest_ocr:
                        ocr_last_submitted.pop(k, None)

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
                            "plate": track_plates.get(track.track_id),
                            "intrusion": (
                                bool(getattr(pipeline.zone, "enabled", True))
                                and pipeline.zone.id != DEFAULT_ZONE.id
                                and track.class_name in {"person", "car", "truck", "bus", "motorcycle"}
                                and (track.track_id in getattr(pipeline, "_active_line_intruders", set()) or getattr(track, "is_intrusion", False))
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
                pass

    with contextlib.suppress(Exception):
        pipeline.warmup()
    with contextlib.suppress(Exception):
        anpr.warmup()

    analysis_thread = threading.Thread(target=analyze, daemon=True, name=f"analysis-{camera_id[:8]}")
    analysis_thread.start()

    if is_file_source:
        file_path_str = _clean_file_path(endpoint)
        p = Path(file_path_str)
        if not p.is_absolute():
            for r in _file_jail_roots():
                sub = (r / p).resolve()
                if sub.exists():
                    file_path_str = str(sub)
                    break
        container = None
        loop_count = 0
        decode_errors = 0

        while not stop.is_set():
            sm = _STATE_MACHINES.get(camera_id)
            if (sm and sm.is_disabled()) or cam.get("desired_state") == "DISABLED":
                break
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

                sm = _STATE_MACHINES.get(camera_id)
                if stop.is_set() or (sm and sm.is_disabled()) or cam.get("desired_state") == "DISABLED":
                    break
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
                                seek_to = playback.pop("seek_to", None) if playback_state == "playing" else playback.get("seek_to")
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
                                next_frame_time = time.perf_counter()
                                continue
                            sm = _STATE_MACHINES.get(camera_id)
                            if stop.is_set() or (sm and sm.is_disabled()) or cam.get("desired_state") == "DISABLED":
                                break
                            cam["observed_state"] = "STREAMING"

                            try:
                                frame = next(frame_iter)
                            except (StopIteration, av.error.EOFError):
                                break

                            image = frame.to_ndarray(format="bgr24")
                            h, w = image.shape[:2]
                            if _STREAM_CLIENT_COUNT.get(camera_id, 0) > 0:
                                preview = cv2.resize(image, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_LINEAR) if w > 1280 else image
                                ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
                                if ok:
                                    frame_bytes = encoded.tobytes()
                                    with condition:
                                        _FRAMES[camera_id] = frame_bytes
                            with condition:
                                _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                                condition.notify_all()
                            _notify_stream_subscribers(camera_id)

                            with analysis_lock:
                                if analysis_frame is not None:
                                    analysis_overwrites += 1
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
                                    "queue_drops": analysis_overwrites,
                                    "ocr_timeouts": ocr_timeouts,
                                    "decode_errors": decode_errors,
                                    "reconnect_count": loop_count,
                                    "stream_epoch": cam["stream_epoch"],
                                    "faces_analyzed": pipeline.faces_analyzed,
                                    "frames_skipped": pipeline.frames_skipped,
                                }
                            )
                            del samples[:-10]

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
        if analysis_thread.is_alive():
            analysis_thread.join(timeout=1.0)
        ocr_executor.shutdown(wait=False, cancel_futures=True)
        _release_pipeline(camera_id, pipeline)
        return

    # Live path (phones, RTSP cams)
    endpoint = normalize_mjpeg_url(str(cam["endpoint"]))
    parsed_endpoint = urlparse(endpoint)
    path_lower = parsed_endpoint.path.lower().rstrip("/")
    is_mjpeg_stream = (
        path_lower in {"/video", "/videofeed", "/mjpegfeed"}
        or parsed_endpoint.port in (4747, 8080)
        or cam.get("source_type") == "smartphone_ip_webcam"
        or cam.get("protocol") == "mjpeg"
        or (parsed_endpoint.scheme in ("http", "mjpeg") and path_lower.endswith((".mjpg", ".mjpeg")))
    )

    stream_opts: dict[str, str] = {
        "timeout": "400000",
        "stimeout": "400000",
        "rw_timeout": "400000",
        "fflags": "nobuffer",
        "flags": "low_delay",
        "max_delay": "500000",
        "probesize": "131072",
        "analyzeduration": "500000",
    }
    if parsed_endpoint.scheme in ("rtsp", "rtsps"):
        stream_opts["rtsp_transport"] = "tcp"

    cam_allowlist = cam.get("_site_cidr_allowlist")
    stream_policy = _policy_from_request(cam_allowlist)
    if parsed_endpoint.scheme in ("http", "https") and not stream_policy.allow_redirects:
        stream_opts["follow_redirects"] = "0"

    open_kwargs: dict[str, Any] = {"options": stream_opts}
    if is_mjpeg_stream:
        open_kwargs["format"] = "mpjpeg"

    reconnect_delay = 1.0
    decode_errors = 0
    reconnect_count = 0
    fps_window_start = time.perf_counter()
    fps_window_count = 0
    measured_source_fps = 30.0

    while not stop.is_set():
        sm = _STATE_MACHINES.get(camera_id)
        if (sm and sm.is_disabled()) or cam.get("desired_state") == "DISABLED":
            break
        container = None
        try:
            pinned_endpoint, _ = pin_stream_url(endpoint, stream_policy, timeout=2.0)
            conn_endpoint = _connect_endpoint({**cam, "endpoint": pinned_endpoint})
            container = av.open(conn_endpoint, **open_kwargs)
            stream = next((s for s in container.streams if s.type == "video"), None)
            if stream is None:
                raise RuntimeError("No video stream")
            sm = _STATE_MACHINES.get(camera_id)
            if stop.is_set() or (sm and sm.is_disabled()) or cam.get("desired_state") == "DISABLED":
                break
            cam["observed_state"] = "STREAMING"
            reconnect_delay = 1.0

            for packet in container.demux(stream):
                if stop.is_set():
                    break

                packet_bytes = bytes(packet)
                soi_idx = packet_bytes.find(b"\xff\xd8")
                eoi_idx = packet_bytes.rfind(b"\xff\xd9")
                is_valid_jpeg = False

                if soi_idx != -1 and eoi_idx > soi_idx:
                    clean_jpeg = packet_bytes[soi_idx : eoi_idx + 2]
                    if len(clean_jpeg) > 100:
                        is_valid_jpeg = True
                        if _STREAM_CLIENT_COUNT.get(camera_id, 0) > 0:
                            with condition:
                                _FRAMES[camera_id] = clean_jpeg
                                _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                                condition.notify_all()
                            _notify_stream_subscribers(camera_id)

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
                        if _STREAM_CLIENT_COUNT.get(camera_id, 0) > 0:
                            preview = cv2.resize(image, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_LINEAR) if w > 1280 else image
                            ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                            if ok:
                                frame_bytes = encoded.tobytes()
                                with condition:
                                    _FRAMES[camera_id] = frame_bytes
                        with condition:
                            _FRAME_VERSIONS[camera_id] = _FRAME_VERSIONS.get(camera_id, 0) + 1
                            condition.notify_all()
                        _notify_stream_subscribers(camera_id)

                    with analysis_lock:
                        if analysis_frame is not None:
                            analysis_overwrites += 1
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
                            "queue_drops": analysis_overwrites,
                            "ocr_timeouts": ocr_timeouts,
                            "decode_errors": decode_errors,
                            "reconnect_count": reconnect_count,
                            "stream_epoch": cam["stream_epoch"],
                        }
                    )
                    del samples[:-10]
        except SSRFError as e:
            logger.error("stream_worker_ssrf_blocked", camera_id=camera_id, error=str(e))
            sm = _STATE_MACHINES.get(camera_id)
            if sm:
                try:
                    sm.transition(CameraState.FAILED, reason="ssrf_blocked", safe_message=str(e))
                except Exception as trans_err:
                    logger.error("sm_transition_failed", error=str(trans_err))
            cam["observed_state"] = "FAILED"
            break
        except Exception:
            if stop.is_set():
                break
            reconnect_count += 1
            ocr_last_submitted.clear()
            cam["observed_state"] = "RECONNECTING"
            if stop.wait(reconnect_delay):
                break
            reconnect_delay = min(reconnect_delay * 1.5, 5.0)
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.close()
    analysis_ready.set()
    if analysis_thread.is_alive():
        analysis_thread.join(timeout=1.0)
    ocr_executor.shutdown(wait=False, cancel_futures=True)
    _release_pipeline(camera_id, pipeline)


def _release_pipeline(camera_id: str, pipeline: object) -> None:
    if _ACTIVE_PIPELINES.get(camera_id) is pipeline:
        _ACTIVE_PIPELINES.pop(camera_id, None)


def _stop_worker(camera_id: str, timeout: float = 3.5) -> bool:
    with _WORKERS_LOCK:
        old = _WORKERS.pop(camera_id, None)
    if old is None:
        return True
    old[0].set()
    old[1].join(timeout=timeout)
    alive = old[1].is_alive()
    if alive:
        with _WORKERS_LOCK:
            _STOPPING_WORKERS.setdefault(camera_id, []).append(old[1])
    return not alive


def _start_camera_worker(camera_id: str) -> None:
    with _WORKERS_LOCK:
        old = _WORKERS.get(camera_id)
        if old is not None and old[1].is_alive():
            return
        stopping = list(_STOPPING_WORKERS.get(camera_id, []))

    # Coordinate with previous stopping threads OUTSIDE the global _WORKERS_LOCK
    # to avoid blocking worker starts/stops for all other cameras
    if stopping:
        for t in stopping:
            if t.is_alive():
                t.join(timeout=3.5)

    with _WORKERS_LOCK:
        old = _WORKERS.get(camera_id)
        if old is not None and old[1].is_alive():
            return
        alive_stopping = [t for t in _STOPPING_WORKERS.get(camera_id, []) if t.is_alive()]
        if alive_stopping:
            _STOPPING_WORKERS[camera_id] = alive_stopping
            logger.warning("refusing_double_spawn_stopping_thread_still_alive", camera_id=camera_id)
            return
        _STOPPING_WORKERS.pop(camera_id, None)

        stop = threading.Event()
        worker = threading.Thread(target=_camera_worker, args=(camera_id, stop), daemon=True, name=f"camera-{camera_id[:8]}")
        _WORKERS[camera_id] = (stop, worker)
        worker.start()


def _is_file_camera(camera_id: str) -> bool:
    cam = _CAMERAS.get(camera_id)
    return bool(cam and (cam.get("source_type") == "video_footage" or cam.get("protocol") == "file"))
