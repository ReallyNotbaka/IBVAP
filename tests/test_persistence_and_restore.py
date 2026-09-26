from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from ibvap.config import DBConfig, Settings
from ibvap.db import dispose_engine, get_sessionmaker
from ibvap.events.outbox import OutboxEntry
from ibvap.models import Camera as DBCamera
from ibvap.models import Outbox as DBOutbox
from ibvap.services.persistence import (
    delete_camera_from_db,
    init_persistence,
    save_camera_to_db,
    save_outbox_event_to_db,
)
from ibvap.services.stream_worker import _CAMERAS, _STATE_MACHINES


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await dispose_engine()


@pytest.mark.asyncio
async def test_persistence_camera_lifecycle_and_restore(tmp_path):
    db_file = tmp_path / "test_persist.db"
    settings = Settings(db=DBConfig(url=f"sqlite+aiosqlite:///{db_file.as_posix()}"))

    # 1. Initialize persistence
    await init_persistence(settings)

    cam_id = str(uuid.uuid4())
    cam_data = {
        "id": cam_id,
        "name": "North Gate Thermal",
        "site_id": "00000000-0000-0000-0000-000000000001",
        "source_type": "smartphone_ip_webcam",
        "endpoint": "synthetic://north_gate",
        "protocol": "http",
        "stream_epoch": 1,
        "desired_state": "STREAMING",
        "observed_state": "STREAMING",
        "fence": {"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], "enabled": True},
    }

    # 2. Save camera to DB
    await save_camera_to_db(cam_data)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        res = await session.execute(select(DBCamera).where(DBCamera.id == uuid.UUID(cam_id)))
        row = res.scalar_one_or_none()
        assert row is not None
        assert row.name == "North Gate Thermal"
        assert row.meta["fence"]["polygon"] == [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]

    # 3. Simulate process restart by clearing in-memory state
    _CAMERAS.pop(cam_id, None)
    _STATE_MACHINES.pop(cam_id, None)
    assert cam_id not in _CAMERAS

    # 4. Re-init persistence (restore)
    await init_persistence(settings)

    # 5. Verify camera was restored into memory
    assert cam_id in _CAMERAS
    restored = _CAMERAS[cam_id]
    assert restored["name"] == "North Gate Thermal"
    assert restored["fence"]["polygon"] == [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    assert cam_id in _STATE_MACHINES

    # 6. Delete camera
    await delete_camera_from_db(cam_id)
    async with sm() as session:
        res = await session.execute(select(DBCamera).where(DBCamera.id == uuid.UUID(cam_id)))
        assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_persistence_outbox_events(tmp_path):
    db_file = tmp_path / "test_events_persist.db"
    settings = Settings(db=DBConfig(url=f"sqlite+aiosqlite:///{db_file.as_posix()}"))

    await init_persistence(settings)

    event_id = str(uuid.uuid4())
    entry = OutboxEntry(
        id=event_id,
        topic="event.created",
        payload={"camera_id": "cam-1", "event_type": "watchlist_hit", "threat_level": "CRITICAL"},
        dedup_key="dedup-123",
        status="pending",
    )

    await save_outbox_event_to_db(entry)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        res = await session.execute(select(DBOutbox).where(DBOutbox.id == uuid.UUID(event_id)))
        row = res.scalar_one_or_none()
        assert row is not None
        assert row.topic == "event.created"
        assert row.payload["event_type"] == "watchlist_hit"
        assert row.dedup_key == "dedup-123"
