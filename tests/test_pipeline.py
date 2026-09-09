from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np
import pytest

from ibvap.core.association import link_synthetic_tracks, project_person_box_from_face
from ibvap.core.detector import MockPersonDetector
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.zone_engine import Zone
from ibvap.events.outbox import clear_all, list_events


def test_pipeline_synthetic_frames_create_one_event() -> None:
    clear_all()
    pipe = MiniPipeline(camera_id="cam-test-1", stream_epoch=0, detector=MockPersonDetector())
    # feed 30 synthetic frames - mock detector will fire between 5-20 and intrusion at central zone
    events = []
    for i in range(30):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # put moving white avatar to ensure mean >0 for some frames
        if 5 <= i <= 20:
            x = int(100 + i * 10)
            cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        ev = pipe.process_frame(frame)
        if ev:
            events.append(ev)
    # at least one intrusion event
    assert len(events) >= 1
    assert events[0]["event_type"] == "zone_intrusion"
    assert events[0]["camera_id"] == "cam-test-1"
    # persisted in outbox
    assert len(list_events()) >= 1
    # dedup: same dedup window should not create duplicate
    from ibvap.events.outbox import transactional_write

    e = {"camera_id": "cam-test-1", "event_type": "zone_intrusion"}
    a = transactional_write(e, dedup_key="dup-key-123")
    b = transactional_write(e, dedup_key="dup-key-123")
    assert a.id == b.id


def test_pipeline_from_real_video_file() -> None:
    clear_all()
    # create temp video file with 16 frames
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)  # noqa: SIM115
    tmp.close()
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
        writer = cv2.VideoWriter(tmp.name, fourcc, 10.0, (640, 480))
        for i in range(16):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.rectangle(frame, (50 + i * 20, 100), (110 + i * 20, 300), (255, 255, 255), -1)
            writer.write(frame)
        writer.release()
        assert os.path.exists(tmp.name)
        pipe = MiniPipeline(camera_id="cam-video-1", detector=MockPersonDetector())
        evs = pipe.process_video_file(tmp.name, max_frames=16)
        # should have at least one intrusion as avatar crosses central zone
        assert len(evs) >= 1
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            os.unlink(tmp.name)


def test_pipeline_zone_intrusion_and_exit_events() -> None:
    """Verify zone intrusion followed by a genuine zone exit (walked out, not vanished)."""
    clear_all()
    inside = (0.3, 0.4, 0.5, 0.8)
    # Constant-size box translating upward slowly enough for the tracker's
    # smoothing to hold one ID (fast jumps split IDs - correct behavior).
    # Foot exits the zone (y<0.20) partway through.
    walk = [(0.3, 0.4 - 0.65 * (k + 1) / 12, 0.5, 0.8 - 0.65 * (k + 1) / 12) for k in range(12)]
    outside = (0.3, -0.25, 0.5, 0.15)
    seq = [inside] * 8 + walk + [outside] * 20 + [None] * 40
    pipe = MiniPipeline(
        camera_id="cam-zone-test",
        stream_epoch=1,
        detector=_ScriptedDetector(seq),
        face_detector=None,
        enable_face=False,
    )
    for _ in range(len(seq)):
        pipe.process_frame(_blank())

    events = list_events()
    event_types = [e["event_type"] for e in events]
    assert "zone_intrusion" in event_types, f"Expected zone_intrusion in {event_types}"
    assert "zone_exit" in event_types, f"Expected genuine zone_exit in {event_types}"
    # Ensure neither zone_intrusion nor zone_exit flooded hundreds of events
    intrusion_count = sum(1 for e in events if e["event_type"] == "zone_intrusion")
    exit_count = sum(1 for e in events if e["event_type"] == "zone_exit")
    assert intrusion_count == 1, f"Expected 1 debounced intrusion, got {intrusion_count}"
    assert exit_count == 1, f"Expected 1 debounced exit, got {exit_count}"


def test_pipeline_line_tripwire_crossing() -> None:
    """Verify that a 2-point line tripwire flags crossing targets as zone intrusions."""
    clear_all()
    pipe = MiniPipeline(camera_id="cam-line-test", stream_epoch=1, detector=MockPersonDetector())
    # Configure a vertical tripwire line at x = 0.25 (x pixel ~ 160)
    pipe.zone = Zone(
        id="zone-tripwire-1",
        name="Perimeter Tripwire",
        polygon=[[0.25, 0.0], [0.25, 1.0]],
        fence_type="line",
    )

    # Feed frames 5..20 where target crosses from x ~ 100 to x ~ 300
    for i in range(25):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if 5 <= i <= 20:
            x = int(100 + i * 10)
            cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        pipe.process_frame(frame)

    events = list_events()
    event_types = [e["event_type"] for e in events]
    assert "zone_intrusion" in event_types, f"Expected zone_intrusion for tripwire crossing in {event_types}"
    intrusions = [e for e in events if e["event_type"] == "zone_intrusion"]
    assert len(intrusions) >= 1
    assert intrusions[0]["explanation"]["rule"] == "tripwire_line_crossing"


def test_pipeline_line_tripwire_exit_and_intruder_cleanup() -> None:
    """Verify that when a line intruder terminates, zone_exit is emitted with rule tripwire_line_exit and tracked set is cleaned up."""
    clear_all()
    pipe = MiniPipeline(camera_id="cam-cleanup-test", stream_epoch=1, detector=MockPersonDetector())
    pipe.zone = Zone(
        id="zone-tripwire-clean",
        name="Perimeter Tripwire",
        polygon=[[0.25, 0.0], [0.25, 1.0]],
        fence_type="line",
    )

    # Frame 1..15: target enters and crosses line
    for i in range(15):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        x = int(120 + i * 10)
        cv2.rectangle(frame, (x, 100), (x + 60, 250), (255, 255, 255), -1)
        pipe.process_frame(frame)

    assert len(pipe._active_line_intruders) >= 1

    # Feed 35 empty frames so track ages out and terminates (max_age=30)
    for _ in range(35):
        empty = np.zeros((480, 640, 3), dtype=np.uint8)
        pipe.process_frame(empty)

    # _active_line_intruders MUST be empty after track termination (no leak)
    assert len(pipe._active_line_intruders) == 0, f"Expected active line intruders to be empty, got {pipe._active_line_intruders}"

    events = list_events()
    exits = [e for e in events if e["event_type"] == "zone_exit"]
    assert len(exits) >= 1
    assert exits[0]["explanation"]["rule"] == "tripwire_line_exit"


class _EmptyDetector:
    """YOLO stub that sees nobody - reproduces face-only close-up frames."""

    model_id = "yolo26n-stub"
    runtime = "cpu"

    def detect(self, frame: np.ndarray, frame_id: int) -> list:
        return []


class _OverlappingPersonDetector:
    """YOLO stub returning a real person box overlapping the test face."""

    model_id = "yolo26n-stub"
    runtime = "cpu"

    def detect(self, frame: np.ndarray, frame_id: int) -> list:
        from ibvap.core.detector import Detection

        return [
            Detection(
                class_id=0,
                class_name="person",
                bbox_norm=(0.30, 0.30, 0.70, 0.85),
                confidence=0.88,
                model_id="yolo26n-stub",
                runtime="cpu",
            )
        ]


class _FaceRowDetector:
    """YuNet stub returning one fixed face row (Lena-like head-and-shoulders face)."""

    # Face pixels on a 640x480 frame -> norm (0.406, 0.356, 0.690, 0.760)
    _ROW = np.array(
        [
            [
                260.0,
                171.0,
                182.0,
                194.0,
                300.0,
                220.0,
                360.0,
                220.0,
                330.0,
                260.0,
                310.0,
                290.0,
                350.0,
                290.0,
                0.91,
            ]
        ],
        dtype=np.float32,
    )

    def setInputSize(self, size: tuple[int, int]) -> None:
        pass

    def detect(self, img: np.ndarray) -> tuple[int, np.ndarray]:
        return 1, self._ROW


def _face_only_pipeline(detector: object) -> MiniPipeline:
    from ibvap.core.face import FaceDetector

    stub = _FaceRowDetector()
    face_detector = FaceDetector.__new__(FaceDetector)
    face_detector.model_path = "stub"
    face_detector.conf_threshold = 0.45
    face_detector._detector = stub  # type: ignore[assignment]
    return MiniPipeline(
        camera_id="cam-face-only",
        stream_epoch=1,
        detector=detector,  # type: ignore[arg-type]
        face_detector=face_detector,
        face_recognizer=None,
        enable_face=True,
        face_stride=1,
        sample_stride=1,
    )


def _textured_frame(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)


def test_project_person_box_from_face_geometry() -> None:
    """Projection must contain the face, stay in [0, 1], and match anthropometrics."""
    face = (0.406, 0.357, 0.691, 0.761)
    body = project_person_box_from_face(face)
    assert body is not None
    x1, y1, x2, y2 = body
    assert 0.0 <= x1 < x2 <= 1.0
    assert 0.0 <= y1 < y2 <= 1.0
    # Face center horizontally inside the projected body, face top below body top
    assert x1 < 0.5485 < x2
    assert y1 < 0.357
    assert body == pytest.approx((0.235, 0.0, 0.862, 1.0))


def test_orphan_face_creates_person_track() -> None:
    """A quality-passed face with no person detection must yield a person track."""
    clear_all()
    pipe = _face_only_pipeline(_EmptyDetector())
    for _ in range(3):
        pipe.process_frame(_textured_frame())
    assert len(pipe.last_faces) == 1
    assert pipe.last_faces[0]["quality_passed"] is True
    assert len(pipe.last_tracks) == 1, f"Expected 1 face-anchored track, got {pipe.last_tracks}"
    trk = pipe.last_tracks[0]
    assert trk.class_name == "person"
    from ibvap.core.association import associate_faces_to_tracks

    assert associate_faces_to_tracks(pipe.last_tracks, pipe.last_faces).get(trk.track_id) is not None


def test_face_overlapping_person_detection_suppresses_synthesis() -> None:
    """A real person box overlapping the face wins - no duplicate virtual track."""
    clear_all()
    pipe = _face_only_pipeline(_OverlappingPersonDetector())
    for _ in range(3):
        pipe.process_frame(_textured_frame())
    assert len(pipe.last_tracks) == 1
    assert pipe.last_tracks[0].bbox_norm == (0.30, 0.30, 0.70, 0.85)


def test_low_quality_face_creates_no_track() -> None:
    """A face failing the quality gate (blank crop) must not anchor a track."""
    clear_all()
    pipe = _face_only_pipeline(_EmptyDetector())
    for _ in range(3):
        pipe.process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
    assert pipe.last_faces and pipe.last_faces[0]["quality_passed"] is False
    assert pipe.last_tracks == []


class _HugeFaceRowDetector:
    """YuNet stub returning an extreme close-up face (fills the frame)."""

    _ROW = np.array(
        [
            [
                30.0,
                5.0,
                580.0,
                445.0,
                250.0,
                150.0,
                430.0,
                150.0,
                340.0,
                280.0,
                280.0,
                360.0,
                400.0,
                360.0,
                0.90,
            ]
        ],
        dtype=np.float32,
    )

    def setInputSize(self, size: tuple[int, int]) -> None:
        pass

    def detect(self, img: np.ndarray) -> tuple[int, np.ndarray]:
        return 1, self._ROW


class _FixedRecognizer:
    """SFace stub returning one fixed embedding for any crop."""

    def __init__(self, feat: np.ndarray) -> None:
        self._feat = np.asarray(feat, dtype=np.float32).reshape(1, 128)

    def align_crop(self, frame: np.ndarray, face_row: object) -> np.ndarray:
        return np.ones((112, 112, 3), dtype=np.uint8)

    def extract_feature(self, aligned: np.ndarray) -> np.ndarray:
        return self._feat


def test_link_synthetic_tracks_uses_overlap_not_gates() -> None:
    """Provenance link: a synthetic track links its overlapping face even past gate scale."""
    from ibvap.core.tracker import Track

    syn_trk = Track(
        track_id=1,
        class_name="person",
        class_id=0,
        bbox_norm=(0.0, 0.0, 0.994, 1.0),
        confidence=0.9,
        synthetic=True,
    )
    huge_face = {
        "bbox_norm": (0.047, 0.010, 0.953, 0.938),
        "confidence": 0.9,
        "quality_passed": True,
    }
    assert link_synthetic_tracks([syn_trk], [huge_face]) == {1: huge_face}

    # Guard: a face overlapping a REAL person track belongs to that track -
    # never link it to the synthetic one (no CRITICAL misattribution).
    real_trk = Track(
        track_id=2,
        class_name="person",
        class_id=0,
        bbox_norm=(0.1, 0.1, 0.3, 0.8),
        confidence=0.9,
    )
    assert link_synthetic_tracks([syn_trk, real_trk], [huge_face]) == {}


def test_extreme_closeup_face_gets_identity() -> None:
    """End-to-end residue proof: face-only extreme close-up yields a track WITH identity."""
    from ibvap.core.face import FaceDetector
    from ibvap.core.watchlist import ThreatLevel, WatchlistEntry, get_watchlist_store

    clear_all()
    rng = np.random.default_rng(11)
    v = rng.standard_normal(128).astype(np.float32)
    feat = v / float(np.linalg.norm(v))
    store = get_watchlist_store()
    store.add_entry(
        WatchlistEntry(
            id="closeup-crit-01",
            name="Close Suspect",
            threat_level=ThreatLevel.CRITICAL,
            notes="Extreme close-up identity test",
            gallery=[feat],
            created_at=1.0,
        )
    )
    try:
        stub = _HugeFaceRowDetector()
        face_detector = FaceDetector.__new__(FaceDetector)
        face_detector.model_path = "stub"
        face_detector.conf_threshold = 0.45
        face_detector._detector = stub  # type: ignore[assignment]
        pipe = MiniPipeline(
            camera_id="cam-closeup-id",
            stream_epoch=1,
            detector=_EmptyDetector(),  # type: ignore[arg-type]
            face_detector=face_detector,
            face_recognizer=_FixedRecognizer(feat),
            enable_face=True,
            face_stride=1,
            sample_stride=1,
        )
        for _ in range(2):
            pipe.process_frame(_textured_frame())
        assert len(pipe.last_tracks) == 1
        trk = pipe.last_tracks[0]
        assert trk.class_name == "person"
        assert trk.identity is not None, "Face-only close-up track must carry an identity"
        assert trk.identity.get("entry_id") == "closeup-crit-01"
    finally:
        store.remove_entry("closeup-crit-01")


class _ScriptedDetector:
    """YOLO stub replaying a per-frame script (None = missed frame)."""

    model_id = "stub"
    runtime = "cpu"

    def __init__(self, script: list) -> None:
        self.script = script
        self.i = 0

    def detect(self, frame: np.ndarray, frame_id: int) -> list:
        from ibvap.core.detector import Detection

        box = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if box is None:
            return []
        return [Detection(class_id=0, class_name="person", bbox_norm=box, confidence=0.9, model_id="s", runtime="c")]


def _blank() -> np.ndarray:
    return np.zeros((480, 640, 3), dtype=np.uint8)


def test_occlusion_inside_does_not_emit_zone_exit() -> None:
    """A track dying while its last box is inside the zone is lost, not exited."""
    from ibvap.core.zone_engine import point_in_polygon

    clear_all()
    pipe = MiniPipeline(
        camera_id="cam-occl-test",
        stream_epoch=1,
        detector=_ScriptedDetector([(0.3, 0.4, 0.5, 0.8)] * 6 + [None] * 40),
        face_detector=None,
        enable_face=False,
    )
    for _ in range(46):
        pipe.process_frame(_blank())
    events = list_events()
    assert [e for e in events if e["event_type"] == "zone_exit"] == []
    lost = [e for e in events if e["event_type"] == "target_lost"]
    assert len(lost) == 1
    b = lost[0]["bbox_norm"]
    assert point_in_polygon((b[0] + b[2]) / 2, b[3], pipe.zone.polygon)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def test_return_after_gap_realerts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Presence must be continuous to stay muted: invisible gaps expire the alert."""
    import ibvap.core.pipeline as pipe_module

    clear_all()
    clock = _FakeClock()
    monkeypatch.setattr(pipe_module.time, "time", clock.time)
    monkeypatch.setattr(pipe_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(pipe_module.time, "perf_counter", clock.perf_counter)
    seq = [(0.3, 0.4, 0.5, 0.8)] * 6 + [None] * 4 + [(0.3, 0.05, 0.5, 0.15)] * 2 + [None] * 4 + [(0.3, 0.4, 0.5, 0.8)] * 8
    pipe = MiniPipeline(camera_id="cam-regap-test", stream_epoch=1, detector=_ScriptedDetector(seq), face_detector=None, enable_face=False)
    for n in range(len(seq)):
        if n == 6:
            clock.now += 10.0  # real gaps take seconds; debounce must be satisfied
        pipe.process_frame(_blank())
    intrusions = [e for e in list_events() if e["event_type"] == "zone_intrusion"]
    assert len(intrusions) == 2


def test_loiter_realerts_new_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new loiter episode (new epoch, reused track id) must persist, not dedup."""
    import ibvap.core.pipeline as pipe_module

    clear_all()
    clock = _FakeClock()
    monkeypatch.setattr(pipe_module.time, "time", clock.time)
    monkeypatch.setattr(pipe_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(pipe_module.time, "perf_counter", clock.perf_counter)
    seq = [(0.3, 0.4, 0.5, 0.8)] * 26
    pipe = MiniPipeline(
        camera_id="cam-loiter-test", stream_epoch=1, detector=_ScriptedDetector(seq), face_detector=None, enable_face=False
    )
    # Custom zone id: the rule-engine mirror only runs for non-default zones.
    pipe.zone = Zone(id="zone-loiter-1", name="Loiter Zone", polygon=[[0.05, 0.2], [0.95, 0.2], [0.95, 1.0], [0.05, 1.0]])
    for _ in range(12):
        pipe.process_frame(_blank())
        clock.now += 1.0
    pipe.reset_epoch(2)
    clock.now += 100.0
    for _ in range(12):
        pipe.process_frame(_blank())
        clock.now += 1.0
    loiters = [e for e in list_events() if e["event_type"] == "suspicious_loitering"]
    assert len(loiters) == 2
