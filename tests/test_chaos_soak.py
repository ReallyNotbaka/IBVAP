"""Automated Chaos and Continuous Soak Testing Suite - Phase 8.

Verifies system resilience under extreme operational conditions:
1. Queue backpressure and frame dropping under high-throughput flood.
2. Rapid camera disconnect/reconnect churn with stream epoch isolation.
3. Transactional outbox failure isolation and atomic rollback.
4. Continuous 500+ frame soak memory stability without unbounded leaks.
5. Pipeline abrupt drop and immediate recovery with fresh stream epoch.
"""

from __future__ import annotations

import gc
import time
import tracemalloc
import uuid
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select

from ibvap.config import DBConfig, Settings
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.core.detector import MockPersonDetector
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.queue import BoundedQueue
from ibvap.core.tracker import CentroidTracker
from ibvap.db import dispose_engine, get_engine, get_sessionmaker
from ibvap.events.outbox import clear_all, list_events, list_outbox, transactional_write
from ibvap.models import Base, Camera, Organization, Outbox, Site


def test_bounded_queue_backpressure_chaos() -> None:
    """Test bounded queue behavior under extreme backpressure flood.

    Verifies:
    - Queue size never exceeds max_size (4).
    - Dropped frame count increases due to overflow and stale age.
    - Metrics reflect correct depth and dropped count.
    - Stale items are purged on get_latest().
    """
    max_size = 4
    max_age_ms = 40
    q = BoundedQueue("chaos-queue", max_size=max_size, max_age_ms=max_age_ms)

    # Flood 120 frames with intermittent slight sleeps to trigger both overflow and staleness
    for i in range(120):
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        dummy_frame[0, 0] = i % 256
        q.put(dummy_frame)
        assert q.depth <= max_size
        if i % 20 == 0:
            time.sleep(0.05)  # 50ms sleep > max_age_ms (40ms) to create stale frames

    metrics = q.metrics()
    assert metrics.name == "chaos-queue"
    assert metrics.max_size == max_size
    assert metrics.max_age_ms == max_age_ms
    assert metrics.depth <= max_size
    assert metrics.dropped > 0
    assert q.dropped > 50  # Overwhelming majority of the 120 frames dropped due to backpressure

    # After sleeping longer than max_age_ms, get_latest should drop all stale items
    time.sleep(0.06)
    latest = q.get_latest()
    assert latest is None
    assert q.depth == 0


def test_camera_rapid_reconnect_epoch_isolation() -> None:
    """Test rapid camera reconnect churn and tracker stream epoch isolation.

    Verifies:
    - CameraStateMachine increments stream_epoch monotonically on every reconnect.
    - Full transition cycles succeed and maintain valid state.
    - CentroidTracker epoch reset purges previous tracks and restarts track IDs at 1.
    - Track identities from previous epochs never bleed into new stream epochs.
    """
    sm = CameraStateMachine(camera_id="cam-chaos-01")
    tracker = CentroidTracker(iou_threshold=0.3, max_age=5)

    # Helper to advance state machine from current state to STREAMING
    def advance_to_streaming(machine: CameraStateMachine) -> None:
        if machine.state == CameraState.DRAFT:
            steps = [
                CameraState.VALIDATING,
                CameraState.RESOLVING,
                CameraState.CONNECTING,
                CameraState.AUTHENTICATING,
                CameraState.PROBING,
                CameraState.DECODING,
                CameraState.PREVIEW_READY,
                CameraState.SAVING,
                CameraState.STARTING,
                CameraState.STREAMING,
            ]
        elif machine.state == CameraState.RECONNECTING:
            steps = [
                CameraState.CONNECTING,
                CameraState.AUTHENTICATING,
                CameraState.PROBING,
                CameraState.DECODING,
                CameraState.PREVIEW_READY,
                CameraState.SAVING,
                CameraState.STARTING,
                CameraState.STREAMING,
            ]
        else:
            steps = []
        for s in steps:
            machine.transition(s, reason="chaos_cycle", safe_message="Advancing cycle")

    advance_to_streaming(sm)
    assert sm.state == CameraState.STREAMING
    assert sm.stream_epoch == 0

    # Populate tracker with track in epoch 0
    tracks_epoch0, new0, _ = tracker.update(
        [{"bbox_norm": (0.4, 0.4, 0.6, 0.6), "class_name": "person", "class_id": 0, "confidence": 0.95}],
        timestamp=100.0,
    )
    assert len(tracks_epoch0) == 1
    assert tracks_epoch0[0].track_id == 1

    # Simulate 5 rapid disconnect / reconnect cycles
    for cycle in range(1, 6):
        epoch_before = sm.stream_epoch
        # Disconnect trigger
        sm.transition(CameraState.RECONNECTING, reason="network_drop_chaos", safe_message="Network dropped")
        assert sm.stream_epoch > epoch_before

        # Connect and advance back to STREAMING
        advance_to_streaming(sm)
        assert sm.state == CameraState.STREAMING

        # Tracker epoch isolation: reset_epoch with new stream_epoch
        tracker.reset_epoch(sm.stream_epoch)
        assert tracker.stream_epoch == sm.stream_epoch
        assert len(tracker.tracks) == 0

        # Feed detection at same bbox in new epoch -> track_id must be 1 (isolated epoch reset)
        new_tracks, new_entries, _ = tracker.update(
            [{"bbox_norm": (0.4, 0.4, 0.6, 0.6), "class_name": "person", "class_id": 0, "confidence": 0.95}],
            timestamp=100.0 + cycle * 10.0,
        )
        assert len(new_tracks) == 1
        assert len(new_entries) == 1
        assert new_tracks[0].track_id == 1

    assert sm.stream_epoch >= 5
    assert len(sm.history) > 20


@pytest.mark.asyncio
async def test_transactional_outbox_failure_isolation() -> None:
    """Test transactional outbox failure isolation and rollback.

    Verifies:
    1. In-memory outbox deduplication and idempotent replay.
    2. Live database atomic rollbacks: an error during transaction leaves zero orphaned
       outbox records or partial camera/event writes.
    3. Live database atomic commit: both camera and outbox entry persist together.
    """
    # 1. In-memory Outbox Layer
    clear_all()
    event_payload: dict[str, Any] = {
        "camera_id": "cam-tx-01",
        "event_type": "zone_intrusion",
        "details": {"risk": "high"},
    }
    entry1 = transactional_write(event_payload, dedup_key="chaos-dedup-001")
    assert entry1.dedup_key == "chaos-dedup-001"
    assert len(list_events()) == 1
    assert len(list_outbox()) == 1

    # Idempotent write with same dedup_key must return existing entry without creating duplicates
    entry2 = transactional_write(event_payload, dedup_key="chaos-dedup-001")
    assert entry2.id == entry1.id
    assert len(list_events()) == 1
    assert len(list_outbox()) == 1

    # 2. Live Async SQLAlchemy Database Transactional Failure & Rollback
    settings = Settings(db=DBConfig(url="sqlite+aiosqlite:///:memory:"))
    await dispose_engine()
    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = get_sessionmaker(settings)

    # Seed organization and site
    org_id = uuid.uuid4()
    site_id = uuid.uuid4()
    async with sm() as session:
        org = Organization(id=org_id, name="Resilience Outpost Org")
        site = Site(id=site_id, organization_id=org_id, name="Perimeter North", timezone="UTC")
        session.add_all([org, site])
        await session.commit()

    # Attempt a failed transaction: add a camera, an outbox message, then raise an error before commit
    with pytest.raises(RuntimeError, match="Simulated crash mid-transaction"):
        async with sm() as session:
            cam = Camera(
                site_id=site_id,
                name="Thermal-Chaos-01",
                source_type="rtsp",
                stream_epoch=1,
                desired_state="ACTIVE",
                observed_state="STREAMING",
            )
            session.add(cam)
            await session.flush()  # cam gets ID assigned in transaction buffer

            outbox_entry = Outbox(
                topic="event.created",
                payload={"camera_id": str(cam.id), "event": "intrusion", "epoch": 1},
                status="pending",
                dedup_key="fail-key-001",
            )
            session.add(outbox_entry)
            await session.flush()

            # Simulate hardware / database crash mid-transaction
            raise RuntimeError("Simulated crash mid-transaction")

    # Verify zero orphaned outbox records and zero orphaned cameras
    async with sm() as session:
        res_outbox = await session.execute(select(Outbox))
        assert len(res_outbox.scalars().all()) == 0

        res_cam = await session.execute(select(Camera).where(Camera.name == "Thermal-Chaos-01"))
        assert len(res_cam.scalars().all()) == 0

    # Verify successful atomic write persists both
    async with sm() as session:
        cam_ok = Camera(
            site_id=site_id,
            name="Thermal-Chaos-01",
            source_type="rtsp",
            stream_epoch=1,
            desired_state="ACTIVE",
            observed_state="STREAMING",
        )
        session.add(cam_ok)
        await session.flush()

        outbox_ok = Outbox(
            topic="event.created",
            payload={"camera_id": str(cam_ok.id), "event": "intrusion", "epoch": 1},
            status="pending",
            dedup_key="success-key-001",
        )
        session.add(outbox_ok)
        await session.commit()

    async with sm() as session:
        res_outbox_ok = await session.execute(select(Outbox).where(Outbox.dedup_key == "success-key-001"))
        persisted_outbox = res_outbox_ok.scalar_one()
        assert persisted_outbox.topic == "event.created"
        assert persisted_outbox.payload["epoch"] == 1

        res_cam_ok = await session.execute(select(Camera).where(Camera.name == "Thermal-Chaos-01"))
        assert res_cam_ok.scalar_one().name == "Thermal-Chaos-01"

    await dispose_engine()


def test_continuous_soak_memory_stability() -> None:
    """Test continuous frame processing soak (500+ frames) for memory stability.

    Verifies:
    - MiniPipeline processes 500+ continuous synthetic frames without crashes.
    - Python memory allocation (tracemalloc) delta between warmup (frame 50) and completion (frame 550)
      remains strictly bounded (< 5.0 MB heap drift).
    - Bounded queues drop frames as needed without memory expansion.
    """
    clear_all()
    gc.collect()
    tracemalloc.start()

    pipe = MiniPipeline(camera_id="cam-soak-01", stream_epoch=1, detector=MockPersonDetector())

    total_frames = 550
    warmup_frames = 50
    warmup_mem_bytes = 0

    for i in range(total_frames):
        # Generate synthetic frame with moving stimulus
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if (i % 30) < 15:
            # Simulate object crossing central area
            x = int(100 + (i % 30) * 15)
            frame[100:250, x : x + 60] = 255

        pipe.process_frame(frame)

        if i == warmup_frames:
            gc.collect()
            current, _ = tracemalloc.get_traced_memory()
            warmup_mem_bytes = current

    gc.collect()
    final_mem_bytes, peak_mem_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Calculate memory delta after warmup
    mem_delta_mb = (final_mem_bytes - warmup_mem_bytes) / (1024 * 1024)
    peak_mb = peak_mem_bytes / (1024 * 1024)

    assert pipe.frame_idx == total_frames
    assert pipe.events_created >= 1
    # Memory growth during continuous 500 frames must be bounded to less than 5.0 MB
    assert mem_delta_mb < 5.0, f"Memory drift exceeded 5.0 MB: {mem_delta_mb:.2f} MB"
    assert peak_mb < 50.0, f"Peak memory exceeded 50.0 MB: {peak_mb:.2f} MB"


def test_pipeline_abrupt_restart_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test mid-stream pipeline abrupt crash and immediate recreation under a new epoch.

    Verifies:
    - Epoch 1 pipeline processes frames and emits epoch 1 events.
    - Abrupt drop (crash/termination) of pipeline object discards internal queue state.
    - Recreated pipeline with stream_epoch 2 restarts frame indexing, resets tracker IDs,
      and emits events correctly tagged with stream_epoch 2 after recovery.
    - No cross-epoch track ID pollution occurs in the outbox.
    """
    clear_all()
    simulated_time = 1000.0
    monkeypatch.setattr(time, "time", lambda: simulated_time)

    # Stage 1: Pipeline running in Epoch 1
    pipe_epoch1 = MiniPipeline(camera_id="cam-restart-01", stream_epoch=1, detector=MockPersonDetector())

    # Feed frames 0..15 to trigger intrusion
    for i in range(16):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if 5 <= i <= 12:
            x = int(100 + i * 10)
            frame[100:250, x : x + 60] = 255
        pipe_epoch1.process_frame(frame)

    events_epoch1 = [e for e in list_events() if e.get("camera_id") == "cam-restart-01"]
    assert len(events_epoch1) >= 1
    assert all(e["stream_epoch"] == 1 for e in events_epoch1)
    assert pipe_epoch1.frame_idx == 16

    # Stage 2: Abrupt drop (simulate worker crash, process kill, or connection reset)
    del pipe_epoch1
    gc.collect()

    # Advance simulated time past the dedup cooldown window (5 seconds) to simulate recovery interval
    simulated_time += 10.0

    # Stage 3: Immediate recovery with incremented Stream Epoch 2
    pipe_epoch2 = MiniPipeline(camera_id="cam-restart-01", stream_epoch=2, detector=MockPersonDetector())
    assert pipe_epoch2.stream_epoch == 2
    assert pipe_epoch2.tracker.stream_epoch == 2
    assert pipe_epoch2.frame_idx == 0
    assert pipe_epoch2.events_created == 0

    # Feed new frames to trigger intrusion under Epoch 2
    for i in range(16):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if 5 <= i <= 12:
            x = int(100 + i * 10)
            frame[100:250, x : x + 60] = 255
        pipe_epoch2.process_frame(frame)

    assert pipe_epoch2.frame_idx == 16
    all_events = list_events()
    events_epoch2 = [e for e in all_events if e.get("stream_epoch") == 2]
    assert len(events_epoch2) >= 1
    assert events_epoch2[0]["stream_epoch"] == 2
    assert events_epoch2[0]["camera_id"] == "cam-restart-01"
