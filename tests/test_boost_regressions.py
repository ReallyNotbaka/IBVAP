"""Regression tests for independently verified confirmed bugs."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient


def test_bug_3_ipv6_url_credentials_preserves_brackets() -> None:
    from ibvap.core.credentials import build_authenticated_url, redact_url

    endpoint = "rtsp://[2001:db8::1]:554/live"
    auth = build_authenticated_url(endpoint, "admin", "secret123")
    assert auth == "rtsp://admin:secret123@[2001:db8::1]:554/live"

    redacted = redact_url("rtsp://admin:secret123@[2001:db8::1]:554/live")
    assert redacted == "rtsp://[2001:db8::1]:554/live"


def test_bug_7_evidence_manifest_snapshot_less_clip(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    from pathlib import Path

    from ibvap.core.evidence import PacketRingBuffer

    evidence_dir = Path("data/evidence_test_bug7")
    shutil.rmtree(evidence_dir, ignore_errors=True)

    ring = PacketRingBuffer(max_seconds=10.0)
    # Monkeypatch the clip path format to point to a non-existent directory
    monkeypatch.setattr(
        "ibvap.core.evidence.Path", lambda p: Path(str(p).replace("data/evidence", "data/evidence_test_bug7"))
    )
    try:
        manifest = ring.manifest_for("ev_nosnap", snap=None, clip=b"testclipdata")
        assert manifest.clip_path is not None
        assert manifest.snapshot_path is None
        assert manifest.clip_sha256 is not None
    finally:
        shutil.rmtree(evidence_dir, ignore_errors=True)


def test_bug_11_video_duration_validation_unit_inversion(monkeypatch: pytest.MonkeyPatch) -> None:
    from fractions import Fraction
    from pathlib import Path

    from ibvap.api.routes.uploads import probe_quarantined_video

    class FakeStream:
        type = "video"
        time_base = Fraction(1, 30)

    class FakeContainer:
        duration = 20_000_000  # 20 seconds in av.time_base microseconds (20s << MAX_DURATION_SECS 600s)
        streams = [FakeStream()]

        def decode(self, stream: object) -> object:
            yield "frame"

        def close(self) -> None:
            pass

    monkeypatch.setattr("av.open", lambda *args, **kwargs: FakeContainer())
    # 20s clip should be valid and NOT raise "Clip exceeds maximum duration"
    # On buggy implementation, 20_000_000 * (1/30) = 666,666s > 600s raises 422!
    probe_quarantined_video(Path("tests/fixtures/test_upload_face.mp4"))


def test_bug_5_bounded_queue_get_latest_no_ghost_drops() -> None:
    from ibvap.core.queue import BoundedQueue

    q = BoundedQueue("telemetry", max_size=2, max_age_ms=400)
    # Put frame 1, read it via get_latest()
    q.put("frame1")
    latest1 = q.get_latest()
    assert latest1 == "frame1"
    assert q.depth == 0  # Queue should be consumed

    # get_latest on now-empty queue returns None
    assert q.get_latest() is None

    # Put frame 2, read it
    q.put("frame2")
    latest2 = q.get_latest()
    assert latest2 == "frame2"
    assert q.depth == 0

    # Put frame 3, read it
    q.put("frame3")
    latest3 = q.get_latest()
    assert latest3 == "frame3"

    # There were zero drops! All frames were consumed in order!
    assert q.dropped == 0


def test_bug_10_military_sitrep_does_not_double_count_vehicle_with_plate() -> None:
    from ibvap.core.sitrep import generate_military_sitrep

    cams = [{"id": "c1", "name": "East Gate", "observed_state": "STREAMING"}]
    obs_map = {
        "c1": {
            "tracks": [
                {
                    "track_id": 10,
                    "class_name": "car",
                    "bbox_norm": [0.2, 0.2, 0.5, 0.8],
                    "confidence": 0.9,
                }
            ],
            "plates": [{"text": "KA01AB1234", "confidence": 0.92}],
        }
    }
    sitrep = generate_military_sitrep(cams, obs_map, unit_name="CHECKPOINT CHARLIE")
    # 1 car with 1 plate must equal 1 motorized target, NOT 2!
    assert sitrep.vehicles_tracked == 1
    assert "TOTAL MOTORIZED TARGETS MONITORED: 1" in sitrep.formatted_text
    assert "KA01AB1234" in sitrep.formatted_text


def test_bug_12_camera_reconnect_epoch_monotonicity() -> None:
    from ibvap.core.camera_state import CameraState, CameraStateMachine

    sm = CameraStateMachine(camera_id="cam-mono")
    sm.state = CameraState.STREAMING
    sm.stream_epoch = 0

    # Execute standard reconnect sequence: RECONNECTING -> CONNECTING -> STREAMING
    sm.transition(CameraState.RECONNECTING, reason="net_drop", safe_message="Reconnecting")
    sm.transition(CameraState.CONNECTING, reason="connecting", safe_message="Connecting")
    sm.transition(CameraState.STREAMING, reason="streaming", safe_message="Streaming")

    # The reconnect sequence must bump stream_epoch monotonically by exactly 1, not skip to 2!
    assert sm.stream_epoch == 1


def test_bug_4_handover_does_not_merge_simultaneous_tracks_on_same_camera() -> None:
    from ibvap.core.handover import HandoverEngine

    engine = HandoverEngine()
    cams = [{"id": "cam-1", "name": "Gate Alpha", "observed_state": "STREAMING"}]

    # Frame with TWO simultaneous persons on the SAME camera
    obs = {
        "cam-1": {
            "tracks": [
                {
                    "track_id": 1,
                    "class_name": "person",
                    "bbox_norm": [0.1, 0.1, 0.2, 0.5],
                    "confidence": 0.9,
                },
                {
                    "track_id": 2,
                    "class_name": "person",
                    "bbox_norm": [0.7, 0.1, 0.8, 0.5],
                    "confidence": 0.88,
                },
            ]
        }
    }
    dossiers = engine.update_observations(cams, obs)
    # Must produce 2 separate dossiers for 2 simultaneous persons on the same camera!
    assert len(dossiers) == 2
    assert dossiers[0].dossier_id != dossiers[1].dossier_id


def test_bug_6_outside_jail_file_endpoint_rejected_by_api(api_client: TestClient) -> None:
    import os
    from pathlib import Path

    import cv2
    import numpy as np

    from ibvap.api.routes import cameras as C

    # Create video file strictly outside jail roots (in user home dir)
    p = Path.home() / f"ibvap_outside_jail_test_{os.getpid()}.mp4"
    resolved = p.resolve()
    assert not any(resolved.is_relative_to(r) for r in C._file_jail_roots())

    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 64))  # pyright: ignore[reportAttributeAccessIssue] # absent from cv2 stubs
    w.write(np.zeros((64, 64, 3), np.uint8))
    w.release()

    try:
        client = api_client
        resp = client.post(
            "/api/v1/cameras",
            json={
                "name": "Outside jail cam",
                "site_id": "00000000-0000-4000-8000-000000000001",
                "source_type": "video_footage",
                "endpoint": str(p),
                "protocol": "file",
            },
        )
        # Outside jail video MUST be rejected with status 400!
        assert resp.status_code == 400
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "invalid_file_path"
    finally:
        p.unlink(missing_ok=True)


def test_bug_2_spurious_amber_match_does_not_strip_critical_identity_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    from ibvap.core.pipeline import MiniPipeline
    from ibvap.core.watchlist import MatchResult, ThreatLevel

    class DummyFaceQuality:
        passed = True
        blur = 100.0
        illumination = 100.0

    class DummyRawFace:
        bbox_norm = (0.62, 0.12, 0.75, 0.25)
        confidence = 0.95
        landmarks = [(0.0, 0.0)] * 5
        quality = DummyFaceQuality()

    class DummyFaceDetector:
        def __init__(self) -> None:
            self.has_face = False

        def detect(self, frame: object) -> list[object]:
            return [DummyRawFace()] if self.has_face else []

    class DummyRecognizer:
        def align_crop(self, frame: object, raw: object) -> np.ndarray:
            return np.zeros((112, 112, 3), dtype=np.uint8)

        def extract_feature(self, img: object) -> np.ndarray:
            return np.zeros((128,), dtype=np.float32)

    class DummyWatchlistStore:
        def identify(self, feat: object) -> MatchResult:
            return MatchResult(
                entry_id="crit-007",
                name="James Bond",
                score=0.42,
                tier="AMBER",
                threat_level=ThreatLevel.CRITICAL,
            )

        def record_sighting(self, entry_id: str, ts: float) -> None:
            pass

    from dataclasses import dataclass

    @dataclass
    class DummyDet:
        bbox_norm: tuple[float, float, float, float]
        class_name: str
        class_id: int
        confidence: float

    class DummyDetector:
        model_id = "dummy-detector"
        input_size = 640

        def detect(self, frame: np.ndarray, frame_id: int = 0) -> list:
            return [
                DummyDet(bbox_norm=(0.1, 0.1, 0.3, 0.5), class_name="person", class_id=0, confidence=0.9),
                DummyDet(bbox_norm=(0.6, 0.1, 0.8, 0.5), class_name="person", class_id=0, confidence=0.85),
            ]

    face_det = DummyFaceDetector()
    pipe = MiniPipeline(
        camera_id="cam-crit",
        stream_epoch=0,
        detector=DummyDetector(),
        face_detector=face_det,
        face_recognizer=DummyRecognizer(),
        enable_face=True,
        sample_stride=1,
        face_stride=1,
    )

    monkeypatch.setattr("ibvap.core.pipeline.get_watchlist_store", lambda: DummyWatchlistStore())

    # Frame 0: initialize tracks without face
    pipe.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
    tracks = {t.track_id: t for t in pipe.last_tracks}
    assert len(tracks) == 2
    t1_id = next(tid for tid, t in tracks.items() if t.bbox_norm[0] < 0.5)
    t2_id = next(tid for tid, t in tracks.items() if t.bbox_norm[0] >= 0.5)

    # Lock Track 1 to CRITICAL watchlist identity
    t1 = pipe.tracker.tracks[t1_id]
    t1.identity_locked = True
    t1.identity = {
        "entry_id": "crit-007",
        "name": "James Bond",
        "threat_level": "CRITICAL",
        "tier": "RED",
        "score": 0.95,
        "locked": True,
    }
    t1.last_bio_frame = 0

    # Frame 1: Track 2 gets an AMBER face match for "crit-007"
    face_det.has_face = True
    pipe.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))

    # Track 1's confirmed CRITICAL lock MUST NOT be stripped by Track 2's spurious AMBER match!
    t1_after = pipe.tracker.tracks.get(t1_id)
    assert t1_after is not None
    assert t1_after.identity_locked is True, "CRITICAL identity lock was stripped by spurious AMBER match!"
    assert t1_after.identity is not None
    assert t1_after.identity.get("entry_id") == "crit-007"

    t2_after = pipe.tracker.tracks.get(t2_id)
    assert t2_after is not None
    assert t2_after.identity_locked is False
    assert t2_after.identity is None


def test_bug_2_spurious_amber_match_arbitration_order_invariant(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the spurious AMBER track appears FIRST in tracker dict, locked CRITICAL track still wins."""

    import numpy as np

    from ibvap.core.pipeline import MiniPipeline
    from ibvap.core.tracker import Track

    pipe = MiniPipeline(camera_id="cam-order", stream_epoch=0)

    # Track 2: unlocked AMBER match inserted FIRST in dict
    t2 = Track(track_id=2, class_name="person", class_id=0, bbox_norm=(0.6, 0.1, 0.8, 0.5), confidence=0.85)
    t2.last_bio_frame = 5  # more recent bio frame!
    t2.identity = {
        "entry_id": "crit-007",
        "name": "James Bond",
        "threat_level": "CRITICAL",
        "tier": "AMBER",
        "score": 0.42,
        "locked": False,
    }
    t2.identity_locked = False

    # Track 1: locked CRITICAL match inserted SECOND in dict
    t1 = Track(track_id=1, class_name="person", class_id=0, bbox_norm=(0.1, 0.1, 0.3, 0.5), confidence=0.9)
    t1.last_bio_frame = 1  # older bio frame!
    t1.identity = {
        "entry_id": "crit-007",
        "name": "James Bond",
        "threat_level": "CRITICAL",
        "tier": "RED",
        "score": 0.95,
        "locked": True,
    }
    t1.identity_locked = True

    pipe.tracker.tracks = {2: t2, 1: t1}
    # Trigger process_frame or run pipeline frame
    pipe.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))

    assert t1.identity_locked is True
    assert t1.identity is not None and t1.identity.get("entry_id") == "crit-007"
    assert t2.identity_locked is False
    assert t2.identity is None


def test_bug_1_camera_disable_stops_worker_and_preserves_disabled_state(api_client: TestClient) -> None:
    from ibvap.api.routes import cameras as C
    from ibvap.core.camera_state import CameraState, CameraStateMachine

    cam_id = "test-cam-disable-bug1"
    sm = CameraStateMachine(camera_id=cam_id)
    sm.state = CameraState.STREAMING
    C._STATE_MACHINES[cam_id] = sm
    C._CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Disable Test Cam",
        "endpoint": "tests/fixtures/test_upload_face.mp4",
        "protocol": "file",
        "source_type": "video_footage",
        "observed_state": "STREAMING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
    }

    try:
        # Start worker
        C._start_camera_worker(cam_id)
        assert cam_id in C._WORKERS
        assert C._WORKERS[cam_id][1].is_alive()

        # Disable camera via API
        client = api_client
        resp = client.post(f"/api/v1/cameras/{cam_id}/disable")
        assert resp.status_code == 200
        assert resp.json()["observed_state"] == "DISABLED"

        # Worker must have been stopped and removed from _WORKERS
        assert cam_id not in C._WORKERS, "Camera disable leaked worker thread in _WORKERS!"

        # Enable camera via API
        resp2 = client.post(f"/api/v1/cameras/{cam_id}/enable")
        assert resp2.status_code == 200
        assert resp2.json()["observed_state"] == "STREAMING"
        # Worker must have been restarted
        assert cam_id in C._WORKERS
        assert C._WORKERS[cam_id][1].is_alive()
    finally:
        C._stop_worker(cam_id)
        C._CAMERAS.pop(cam_id, None)
        C._STATE_MACHINES.pop(cam_id, None)


def test_bug_14_concurrent_reconnect_no_double_spawn(api_client: TestClient) -> None:
    import concurrent.futures
    import threading

    from ibvap.api.routes import cameras as C
    from ibvap.core.camera_state import CameraState, CameraStateMachine

    cam_id = "test-cam-rec-b14"
    sm = CameraStateMachine(camera_id=cam_id)
    sm.state = CameraState.STREAMING
    C._STATE_MACHINES[cam_id] = sm
    C._CAMERAS[cam_id] = {
        "id": cam_id,
        "name": "Reconnect Concurrency Test",
        "endpoint": "tests/fixtures/test_upload_face.mp4",
        "protocol": "file",
        "source_type": "video_footage",
        "observed_state": "STREAMING",
        "desired_state": "STREAMING",
        "stream_epoch": 0,
    }

    client = api_client
    C._start_camera_worker(cam_id)
    assert cam_id in C._WORKERS

    try:

        def do_reconnect() -> None:
            client.post(f"/api/v1/cameras/{cam_id}/reconnect")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(do_reconnect) for _ in range(10)]
            concurrent.futures.wait(futs)

        # Give a moment for any stopping threads to exit
        import time

        time.sleep(0.5)

        active_threads = [t for t in threading.enumerate() if t.name == f"camera-{cam_id[:8]}" and t.is_alive()]
        assert len(active_threads) == 1, f"Expected 1 alive camera worker thread, found {len(active_threads)}"
    finally:
        C._stop_worker(cam_id)
        C._CAMERAS.pop(cam_id, None)
        C._STATE_MACHINES.pop(cam_id, None)
