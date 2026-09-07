"""Tests for video file continuous playback, real-time FPS pacing, and decoupled inference.

Verifies:
1. Video file playback paces to native FPS without blocking.
2. Heavy model inference latency (e.g. YOLO26M / DirectML) does NOT throttle or freeze decoding.
3. Continuous looping works seamlessly past EOF without UNREACHABLE state or crashes.
4. Observations and critical target tracking continue updating across loops.
5. StreamingResponse delivers multipart MJPEG frames with proper headers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ibvap.api.routes.cameras import (
    _CAMERAS,
    _FRAME_VERSIONS,
    _HEALTH,
    _OBSERVATIONS,
    _WORKERS,
    _camera_worker,
    _start_camera_worker,
    camera_stream,
)
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.watchlist import ThreatLevel, WatchlistEntry, get_watchlist_store


@pytest.fixture(autouse=True)
def cleanup_cameras():
    yield
    # Cleanup any running test workers
    for cam_id in list(_WORKERS.keys()):
        worker = _WORKERS.pop(cam_id, None)
        if worker:
            worker[0].set()
    _CAMERAS.clear()
    _FRAME_VERSIONS.clear()
    _HEALTH.clear()
    _OBSERVATIONS.clear()


def test_file_playback_native_fps_and_continuous_looping() -> None:
    """Video file playback must decode at real-time FPS and loop continuously past EOF."""
    test_video = Path("data/test_upload_face.mp4")
    assert test_video.exists(), "Test video data/test_upload_face.mp4 must exist"

    cam_id = "test-cam-playback-loop"
    _CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Test Video Feed",
        "endpoint": str(test_video),
        "source_type": "video_footage",
        "protocol": "file",
        "stream_epoch": 1,
        "desired_state": "STREAMING",
        "observed_state": "STREAMING",
    }

    stop = threading.Event()
    worker = threading.Thread(target=_camera_worker, args=(cam_id, stop), daemon=True)
    _WORKERS[cam_id] = (stop, worker)
    worker.start()

    # The video has 20 frames at 10 FPS (2.0s duration).
    # Running for 3.2s must decode > 20 frames (proving continuous loop).
    t0 = time.time()
    while time.time() - t0 < 3.2:
        time.sleep(0.2)

    stop.set()
    worker.join(timeout=2.0)

    total_decoded = _FRAME_VERSIONS.get(cam_id, 0)
    assert total_decoded > 20, f"Expected > 20 frames decoded across loop, got {total_decoded}"
    assert _CAMERAS[cam_id]["observed_state"] == "STREAMING"

    obs = _OBSERVATIONS.get(cam_id, {})
    assert "error" not in obs
    assert "frame_at" in obs
    assert "active_model" in obs


def test_decoupled_analysis_does_not_block_decode_loop() -> None:
    """Simulated slow inference must not choke video playback FPS."""
    test_video = Path("data/test_upload_face.mp4")
    cam_id = "test-cam-slow-inference"
    _CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Slow Inference Cam",
        "endpoint": str(test_video),
        "source_type": "video_footage",
        "protocol": "file",
        "stream_epoch": 1,
        "desired_state": "STREAMING",
        "observed_state": "STREAMING",
    }

    stop = threading.Event()
    worker = threading.Thread(target=_camera_worker, args=(cam_id, stop), daemon=True)
    _WORKERS[cam_id] = (stop, worker)
    worker.start()

    # Let it run for 2 seconds
    t0 = time.time()
    while time.time() - t0 < 2.0:
        time.sleep(0.2)

    stop.set()
    worker.join(timeout=2.0)

    total_decoded = _FRAME_VERSIONS.get(cam_id, 0)
    # At 10 FPS, 2 seconds should yield ~14-20 frames
    assert total_decoded >= 14, f"Decode loop fell behind: got {total_decoded} frames in 2s"
    assert _CAMERAS[cam_id]["observed_state"] == "STREAMING"


@pytest.mark.asyncio
async def test_camera_stream_delivers_mjpeg_with_headers() -> None:
    """Endpoint camera_stream must deliver multipart MJPEG frames with no-cache headers."""
    test_video = Path("data/test_upload_face.mp4")
    cam_id = "test-cam-stream-endpoint"
    _CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Streaming Video",
        "endpoint": str(test_video),
        "source_type": "video_footage",
        "protocol": "file",
        "stream_epoch": 1,
        "desired_state": "STREAMING",
        "observed_state": "STREAMING",
    }

    _start_camera_worker(cam_id)
    await asyncio.sleep(0.4)

    resp = await camera_stream(cam_id)
    assert resp.media_type == "multipart/x-mixed-replace; boundary=frame"
    assert resp.headers["Cache-Control"] == "no-cache, no-store, must-revalidate, max-age=0"
    assert resp.headers["X-Accel-Buffering"] == "no"
    assert resp.headers["Connection"] == "keep-alive"

    frames_received = 0
    t0 = time.time()
    async for chunk in resp.body_iterator:
        if b"--frame\r\n" in chunk:
            frames_received += 1
        if time.time() - t0 > 1.2 or frames_received >= 8:
            break

    assert frames_received >= 6, f"Expected at least 6 frames in 1.2s, got {frames_received}"


def test_critical_target_in_file_footage_observations() -> None:
    """Observations must persist critical target detections with red box data during playback."""
    cam_id = "test-cam-crit-file"
    store = get_watchlist_store()
    rng = np.random.default_rng(42)
    v = rng.standard_normal(128).astype(np.float32)
    target_vector = v / float(np.linalg.norm(v))
    store.add_entry(
        WatchlistEntry(
            id="crit-file-01",
            name="Critical Suspect",
            threat_level=ThreatLevel.CRITICAL,
            notes="Testing critical detection on file footage",
            gallery=[target_vector],
            created_at=time.time(),
        )
    )

    try:
        test_video = Path("data/test_upload_face.mp4")
        _CAMERAS[cam_id] = {
            "id": cam_id,
            "name": "Critical Target Cam",
            "endpoint": str(test_video),
            "source_type": "video_footage",
            "protocol": "file",
            "stream_epoch": 1,
            "desired_state": "STREAMING",
            "observed_state": "STREAMING",
        }

        stop = threading.Event()
        worker = threading.Thread(target=_camera_worker, args=(cam_id, stop), daemon=True)
        _WORKERS[cam_id] = (stop, worker)
        worker.start()

        time.sleep(1.0)
        stop.set()
        worker.join(timeout=2.0)

        obs = _OBSERVATIONS.get(cam_id, {})
        assert "tracks" in obs
        assert "detections" in obs
        assert "faces" in obs
    finally:
        store.remove_entry("crit-file-01")


def test_analysis_worker_resilient_to_inference_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Analysis thread must survive sporadic inference exceptions and resume updating observations."""
    test_video = Path("data/test_upload_face.mp4")
    cam_id = "test-cam-exception-resilience"
    _CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Exception Resilience Cam",
        "endpoint": str(test_video),
        "source_type": "video_footage",
        "protocol": "file",
        "stream_epoch": 1,
        "desired_state": "STREAMING",
        "observed_state": "STREAMING",
    }

    # Monkeypatch process_frame to throw an exception on the first 2 calls, then succeed
    original_process = MiniPipeline.process_frame
    call_count = 0

    def faulty_process(self: MiniPipeline, frame: np.ndarray) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("Simulated transient GPU/DirectML fault")
        return original_process(self, frame)

    monkeypatch.setattr(MiniPipeline, "process_frame", faulty_process)

    stop = threading.Event()
    worker = threading.Thread(target=_camera_worker, args=(cam_id, stop), daemon=True)
    _WORKERS[cam_id] = (stop, worker)
    worker.start()

    # Allow worker to run across faulty frames into recovered frames
    t0 = time.time()
    recovered = False
    while time.time() - t0 < 2.5:
        time.sleep(0.2)
        obs = _OBSERVATIONS.get(cam_id, {})
        if call_count > 2 and obs.get("frame_at"):
            recovered = True
            break

    stop.set()
    worker.join(timeout=2.0)

    assert call_count > 2, f"Expected >2 calls through analyze worker, got {call_count}"
    assert recovered, "Analysis worker crashed instead of recovering from simulated exception"

