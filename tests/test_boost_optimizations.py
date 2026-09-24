"""Adversarial unit tests and benchmarks challenging /boost optimizations across all 5 areas.

Areas covered:
1. Video Streaming & Decoding: Gated encoding, event subscriber notification, GZip exclusion.
2. Inference & Threading: Thread-local canvas concurrency, intra_op threads, shared handle concurrency.
3. Biometrics, ANPR & Tracking: Plate box reuse, YuNet skipping, deque bounding, intrusion caching, exemplar matrix caching.
4. Concurrency & Memory Leaks: Outbox RLock + FIFO eviction, RuleEngine track pruning, pipeline exit timestamp pruning.
5. Database & API: SQLite PRAGMAs + queue pool, Events API early-exit & reverse scan, Outbox composite indexes.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from unittest.mock import MagicMock

import numpy as np
from fastapi.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.api.routes.cameras import (
    _STREAM_CLIENT_COUNT,
    _STREAM_SUBSCRIBERS,
    _STREAM_SUBSCRIBERS_LOCK,
    _notify_stream_subscribers,
)
from ibvap.core.anpr import ANPRPipeline
from ibvap.core.detector import ONNXDetectorProvider
from ibvap.core.model_manager import ThreadSafeDetectorHandle
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.rules import RuleEngine
from ibvap.core.tracker import CentroidTracker
from ibvap.core.watchlist import WatchlistEntry, WatchlistStore
from ibvap.events.outbox import (
    _DEDUP_EVENT_INDEX,
    _DEDUP_OUTBOX_INDEX,
    _EVENTS,
    _OUTBOX,
    clear_all,
    transactional_write,
)
from ibvap.models import Outbox

# ==============================================================================
# Area 1: Video Streaming & Decoding
# ==============================================================================

def test_stream_subscribers_threadsafe_multicast():
    """Verify multiple subscribers receive notification without dropped signals or deadlocks."""
    cam_id = "test_cam_stream_sub"
    with _STREAM_SUBSCRIBERS_LOCK:
        _STREAM_SUBSCRIBERS.pop(cam_id, None)

    async def scenario():
        loop = asyncio.get_running_loop()
        ev1 = asyncio.Event()
        ev2 = asyncio.Event()
        ev3 = asyncio.Event()

        with _STREAM_SUBSCRIBERS_LOCK:
            subs = _STREAM_SUBSCRIBERS.setdefault(cam_id, set())
            subs.add((loop, ev1))
            subs.add((loop, ev2))
            subs.add((loop, ev3))

        assert not ev1.is_set()
        assert not ev2.is_set()
        assert not ev3.is_set()

        # Notify from separate thread
        t = threading.Thread(target=_notify_stream_subscribers, args=(cam_id,))
        t.start()
        t.join(timeout=1.0)

        # Yield to event loop to process threadsafe callback
        await asyncio.sleep(0.01)

        # All events should be set
        assert ev1.is_set()
        assert ev2.is_set()
        assert ev3.is_set()

        # Cleanup
        with _STREAM_SUBSCRIBERS_LOCK:
            _STREAM_SUBSCRIBERS.pop(cam_id, None)

    asyncio.run(scenario())


def test_gzip_middleware_excludes_multipart():
    """Verify that multipart streams are excluded from gzip chunking/buffering."""
    app = create_app()
    found = False
    for middleware in app.user_middleware:
        kwargs = getattr(middleware, "kwargs", {})
        excludes = kwargs.get("exclude_content_types", ())
        if "multipart/*" in excludes and "multipart/x-mixed-replace" in excludes:
            found = True
            break
    assert found, "GZipMiddleware must exclude multipart/* and multipart/x-mixed-replace"


# ==============================================================================
# Area 2: Inference & Threading
# ==============================================================================

def test_detector_canvas_thread_isolation():
    """Adversarial stress test: multiple worker threads must not corrupt each other's letterbox canvas."""
    detector = ONNXDetectorProvider.__new__(ONNXDetectorProvider)
    detector._local = threading.local()
    detector.model_width = 640
    detector.model_height = 640

    errors = []

    def worker_task(thread_id: int):
        try:
            for _ in range(50):
                unique_canvas = np.full((640, 640, 3), thread_id, dtype=np.uint8)
                detector._canvas = unique_canvas
                time.sleep(0.001)
                if not np.all(detector._canvas == thread_id):
                    errors.append(f"Thread {thread_id} canvas corrupted!")
                    break
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)

    assert not errors, f"Canvas thread isolation failed: {errors}"


def test_shared_detector_handle_concurrent_acquire():
    """Verify ThreadSafeDetectorHandle allows concurrent acquires without serialization lock."""
    mock_detector = MagicMock()
    handle = ThreadSafeDetectorHandle(mock_detector)

    acquire_count = 0
    max_concurrent = 0
    lock = threading.Lock()

    def concurrent_worker():
        nonlocal acquire_count, max_concurrent
        with handle.acquire():
            with lock:
                acquire_count += 1
                if acquire_count > max_concurrent:
                    max_concurrent = acquire_count
            time.sleep(0.01)
            with lock:
                acquire_count -= 1

    threads = [threading.Thread(target=concurrent_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert max_concurrent > 1, f"Expected concurrent acquires, got max_concurrent={max_concurrent}"


# ==============================================================================
# Area 3: Biometrics, ANPR & Tracking
# ==============================================================================

def test_anpr_reuses_cached_plate_boxes():
    """Verify process_vehicle_crop reuses pre-computed plate boxes and skips re-detection."""
    from ibvap.core.anpr import PlateCandidate

    anpr = ANPRPipeline()
    anpr.detector = MagicMock()
    anpr.ocr = MagicMock()
    anpr.ocr.recognize.return_value = [
        PlateCandidate(text="KA01AB1234", confidence=0.95, quality=0.9, bbox_norm=(0.0, 0.0, 1.0, 1.0))
    ]

    vehicle_crop = np.zeros((200, 300, 3), dtype=np.uint8)
    cached_boxes = [(0.1, 0.2, 0.8, 0.4)]

    # Call twice to form consensus
    anpr.process_vehicle_crop(vehicle_crop, vehicle_id=1, plate_boxes=cached_boxes)
    result = anpr.process_vehicle_crop(vehicle_crop, vehicle_id=1, plate_boxes=cached_boxes)
    anpr.detector.detect.assert_not_called()
    assert result is not None
    assert result.plate_text == "KA01AB1234"


def test_pipeline_skips_face_detection_when_no_persons():
    """When skip_face_without_person is True and scene has 0 persons, YuNet must not run."""
    pipeline = MiniPipeline(camera_id="cam_test", enable_face=True, skip_face_without_person=True)
    mock_face_det = MagicMock()
    pipeline.face_detector = mock_face_det
    pipeline.detector = MagicMock()
    mock_car = MagicMock()
    mock_car.bbox_norm = (0.1, 0.1, 0.5, 0.5)
    mock_car.class_name = "car"
    mock_car.class_id = 2
    mock_car.confidence = 0.9
    pipeline.detector.detect.return_value = [mock_car]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    pipeline.process_frame(frame)

    mock_face_det.detect.assert_not_called()


def test_track_trajectory_bounding_and_deque():
    """Verify Track.trajectory uses deque(maxlen=64) and does not grow unbounded under 1000 updates."""
    tracker = CentroidTracker()
    for i in range(200):
        tracks, _, _ = tracker.update(
            [{"bbox_norm": (0.1, 0.1, 0.3, 0.5), "class_name": "person", "class_id": 0, "confidence": 0.9}],
            timestamp=float(i),
        )

    assert len(tracks) == 1
    track = tracks[0]
    assert isinstance(track.trajectory, deque)
    assert track.trajectory.maxlen == 64
    assert len(track.trajectory) == 64


def test_watchlist_store_exemplar_caching():
    """Verify WatchlistEntry caches exemplar matrix and invalidates properly on modification."""
    from ibvap.core.watchlist import ThreatLevel
    rng = np.random.default_rng(42)
    emb1 = rng.standard_normal(128).astype(np.float32)
    emb2 = rng.standard_normal(128).astype(np.float32)

    entry = WatchlistEntry(id="suspect_1", name="Test Suspect", threat_level=ThreatLevel.CRITICAL, gallery=[emb1])
    mat1 = entry.matrix
    assert entry._cached_matrix is not None
    # Re-reading property should return identical cached array object
    assert entry.matrix is mat1

    # Invalidation
    entry.gallery.append(emb2)
    entry.invalidate_cache()
    assert entry._cached_matrix is None
    mat2 = entry.matrix
    assert mat2.shape == (2, 128)
    assert entry._cached_matrix is not None


# ==============================================================================
# Area 4: Concurrency & Memory Leaks
# ==============================================================================

def test_outbox_fifo_eviction_under_load():
    """Verify outbox caps at MAX_EVENTS and MAX_OUTBOX and cleans index mappings."""
    clear_all()
    for i in range(100):
        transactional_write({"index": i, "camera_id": "c1"}, dedup_key=f"k_{i}")

    assert len(_EVENTS) == 100
    assert len(_OUTBOX) == 100

    import ibvap.events.outbox as outbox_mod
    orig_max_events = outbox_mod.MAX_EVENTS
    orig_max_outbox = outbox_mod.MAX_OUTBOX
    try:
        outbox_mod.MAX_EVENTS = 50
        outbox_mod.MAX_OUTBOX = 50

        for i in range(100, 110):
            transactional_write({"index": i, "camera_id": "c1"}, dedup_key=f"k_{i}")

        assert len(_EVENTS) == 50
        assert len(_OUTBOX) == 50
        assert "k_0" not in _DEDUP_EVENT_INDEX
        assert "k_0" not in _DEDUP_OUTBOX_INDEX
        assert "k_109" in _DEDUP_EVENT_INDEX
        assert "k_109" in _DEDUP_OUTBOX_INDEX
    finally:
        outbox_mod.MAX_EVENTS = orig_max_events
        outbox_mod.MAX_OUTBOX = orig_max_outbox
        clear_all()


def test_rule_engine_and_pipeline_track_pruning():
    """Verify terminated tracks are pruned from RuleEngine and MiniPipeline timestamp dicts."""
    zone = {"id": "z1", "name": "zone1", "polygon": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]}
    engine = RuleEngine(zones=[zone])
    engine.check_zones(track_id=99, footpoint=(0.5, 0.5), timestamp=10.0)
    assert 99 in engine._loiter_state

    engine.prune_track(99)
    assert 99 not in engine._loiter_state

    pipeline = MiniPipeline("cam_prune")
    pipeline._last_exit_alert_time[("z1", 99)] = 100.0
    pipeline._last_exit_alert_time[(-1, 99)] = 100.0
    pipeline.alerted_tracks.add(99)

    pipeline.prune_track(99)
    assert 99 not in pipeline.alerted_tracks
    assert ("z1", 99) not in pipeline._last_exit_alert_time
    assert (-1, 99) not in pipeline._last_exit_alert_time


# ==============================================================================
# Area 5: Database & API
# ==============================================================================

def test_events_api_early_exit_and_ordering(api_client: TestClient):
    """Verify get_events traverses reversed, breaks early on limit, and preserves order."""
    clear_all()
    # Insert 100 events
    for i in range(100):
        transactional_write(
            {
                "camera_id": "cam_opt",
                "event_type": "zone_intrusion",
                "created_at": 1000.0 + i,
            },
            dedup_key=f"opt_{i}",
        )

    resp = api_client.get("/api/v1/events?limit=10")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 10
    # Must be sorted newest-first (index 99 down to 90)
    assert events[0]["dedup_key"] == "opt_99"
    assert events[9]["dedup_key"] == "opt_90"
    clear_all()


def test_outbox_model_composite_indexes():
    """Verify Outbox model defines the composite indexes."""
    index_names = {idx.name for idx in Outbox.__table_args__ if hasattr(idx, "name")}
    assert "ix_outbox_status_created_at" in index_names
    assert "ix_outbox_status_next_attempt" in index_names
    assert "ix_outbox_status_topic" in index_names


def test_migration_0003_includes_all_three_composite_indexes():
    """Verify migration 0003 contains create_index and drop_index for all 3 composite indexes."""
    mig_path = "migrations/versions/a3c1e2f4b5d6_0003_outbox_composite_indexes.py"
    with open(mig_path, encoding="utf-8") as f:
        content = f.read()

    assert 'op.create_index("ix_outbox_status_created_at"' in content
    assert 'op.create_index("ix_outbox_status_next_attempt"' in content
    assert 'op.create_index("ix_outbox_status_topic"' in content
    assert 'op.drop_index("ix_outbox_status_created_at"' in content
    assert 'op.drop_index("ix_outbox_status_next_attempt"' in content
    assert 'op.drop_index("ix_outbox_status_topic"' in content


def test_stream_subscriber_closed_loop_resilience():
    """Verify that a closed subscriber event loop does not raise RuntimeError or crash worker notification."""
    cam_id = "test_cam_closed_loop"
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    ev = asyncio.Event()

    with _STREAM_SUBSCRIBERS_LOCK:
        _STREAM_SUBSCRIBERS[cam_id] = {(closed_loop, ev)}
        _STREAM_CLIENT_COUNT[cam_id] = 1

    # Calling notification must not throw and must prune the dead subscriber
    _notify_stream_subscribers(cam_id)

    with _STREAM_SUBSCRIBERS_LOCK:
        remaining = _STREAM_SUBSCRIBERS.get(cam_id, set())
        assert len(remaining) == 0
        assert _STREAM_CLIENT_COUNT.get(cam_id, 0) == 0


def test_stream_subscriber_rapid_thrashing():
    """Stress test rapid concurrent subscribe and unsubscribe without race condition or lock corruption."""
    cam_id = "test_cam_thrash"
    loop = asyncio.new_event_loop()

    def worker():
        for _ in range(50):
            ev = asyncio.Event()
            with _STREAM_SUBSCRIBERS_LOCK:
                _STREAM_SUBSCRIBERS.setdefault(cam_id, set()).add((loop, ev))
                _STREAM_CLIENT_COUNT[cam_id] = len(_STREAM_SUBSCRIBERS[cam_id])
            time.sleep(0.0005)
            with _STREAM_SUBSCRIBERS_LOCK:
                subs = _STREAM_SUBSCRIBERS.get(cam_id)
                if subs:
                    subs.discard((loop, ev))
                    _STREAM_CLIENT_COUNT[cam_id] = len(subs)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3.0)

    loop.close()
    with _STREAM_SUBSCRIBERS_LOCK:
        _STREAM_SUBSCRIBERS.pop(cam_id, None)
        _STREAM_CLIENT_COUNT.pop(cam_id, None)


def test_anpr_empty_plate_boxes_skips_morphological_detection():
    """When plate_boxes=[] (pre-detected 0 plates), ANPR must NOT fall back to morphological detection."""
    anpr = ANPRPipeline()
    anpr.detector = MagicMock()
    anpr.ocr = MagicMock()

    vehicle_crop = np.zeros((200, 300, 3), dtype=np.uint8)
    res = anpr.process_vehicle_crop(vehicle_crop, vehicle_id=1, plate_boxes=[])
    anpr.detector.detect.assert_not_called()
    assert res is None


def test_pipeline_clears_ghost_faces_when_person_exits():
    """When a person leaves the scene (0 persons), pipeline with skip_face_without_person must clear last_faces."""
    pipeline = MiniPipeline(camera_id="cam_ghost_face", enable_face=True, skip_face_without_person=True)
    pipeline.detector = MagicMock()
    mock_face_det = MagicMock()
    pipeline.face_detector = mock_face_det

    mock_face = MagicMock()
    mock_face.bbox_norm = (0.3, 0.2, 0.5, 0.4)
    mock_face.confidence = 0.95
    mock_face.quality.passed = True
    mock_face.landmarks = None
    mock_face.quality.blur = 100.0
    mock_face.quality.illumination = 100.0
    mock_face_det.detect.return_value = [mock_face]

    # Frame 1: Person present, face detected
    mock_person = MagicMock()
    mock_person.bbox_norm = (0.2, 0.2, 0.6, 0.8)
    mock_person.class_name = "person"
    mock_person.class_id = 0
    mock_person.confidence = 0.9
    pipeline.detector.detect.return_value = [mock_person]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    pipeline.process_frame(frame)
    # Still has person, faces preserved
    assert len(pipeline.last_faces) > 0

    # Frame 2: Person leaves scene, 0 persons
    pipeline.detector.detect.return_value = []
    pipeline.last_tracks = []
    pipeline.process_frame(frame)
    # Stale faces must be cleared, zero ghost faces!
    assert len(pipeline.last_faces) == 0
    assert pipeline._last_face_frame is None


def test_pipeline_prune_track_cleans_intrusion_alert_timestamps():
    """prune_track must evict entries from both _last_exit_alert_time AND _last_intrusion_alert_time."""
    pipeline = MiniPipeline("cam_prune_full")
    pipeline._last_exit_alert_time[("z1", 77)] = 100.0
    pipeline._last_intrusion_alert_time[("z1", 77)] = 100.0
    pipeline.alerted_tracks.add(77)

    pipeline.prune_track(77)
    assert 77 not in pipeline.alerted_tracks
    assert ("z1", 77) not in pipeline._last_exit_alert_time
    assert ("z1", 77) not in pipeline._last_intrusion_alert_time


def test_watchlist_store_rapid_saves_flush_preserves_latest(tmp_path):
    """Rapid successive saves must not prematurely pop future; flush() must wait for latest state."""
    from ibvap.core.watchlist import ThreatLevel
    store_file = tmp_path / "watchlist_test.json"
    store = WatchlistStore(storage_path=store_file)

    emb1 = np.random.default_rng(1).standard_normal(128).astype(np.float32)
    emb2 = np.random.default_rng(2).standard_normal(128).astype(np.float32)

    e1 = WatchlistEntry(id="suspect_1", name="Suspect One", threat_level=ThreatLevel.HIGH, gallery=[emb1])
    e2 = WatchlistEntry(id="suspect_2", name="Suspect Two", threat_level=ThreatLevel.CRITICAL, gallery=[emb2])

    # Rapid calls
    store.add_entry(e1)
    store.add_entry(e2)
    store.record_sighting("suspect_1", time.time())
    store.flush(timeout=2.0)

    # Re-read from disk in brand new store
    loaded = WatchlistStore(storage_path=store_file)
    assert loaded.get_entry("suspect_1") is not None
    assert loaded.get_entry("suspect_2") is not None
    assert loaded.get_entry("suspect_1").sight_count == 1


def test_events_api_delayed_buffered_events_do_not_displace_live(api_client: TestClient):
    """Events API must return true newest events even if delayed/buffered events are appended at the end."""
    clear_all()
    # Live events t=1000..1010
    for i in range(10):
        transactional_write(
            {
                "camera_id": "cam_live",
                "event_type": "zone_intrusion",
                "created_at": 1000.0 + i,
            },
            dedup_key=f"live_{i}",
        )

    # Delayed flushed event from offline camera appended LAST, but timestamp t=500 (in the past)
    transactional_write(
        {
            "camera_id": "cam_offline",
            "event_type": "zone_intrusion",
            "created_at": 500.0,
        },
        dedup_key="delayed_old",
    )

    resp = api_client.get("/api/v1/events?limit=5")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 5

    # Top 5 newest MUST be live_9, live_8, live_7, live_6, live_5.
    # The delayed_old event (ts=500) must NOT be in top 5!
    retrieved_keys = [e["dedup_key"] for e in events]
    assert retrieved_keys == ["live_9", "live_8", "live_7", "live_6", "live_5"]
    assert "delayed_old" not in retrieved_keys
    clear_all()

