from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ibvap.config import DBConfig, Settings
from ibvap.db import dispose_engine, get_engine, get_session, get_sessionmaker
from ibvap.models import (
    Base,
    Camera,
    CameraHealthSample,
    ConnectionTest,
    CredentialReference,
    Organization,
    Outbox,
    Site,
)


@pytest.fixture(autouse=True)
async def cleanup_db_engine():
    yield
    await dispose_engine()


@pytest.mark.asyncio
async def test_live_db_schema_creation_and_crud(memory_db):
    sm = memory_db

    # 1. Create Organization
    async with sm() as session:
        org = Organization(name="Northern Border Command")
        session.add(org)
        await session.commit()
        org_id = org.id
        assert org_id is not None

    # 2. Query Organization and Add Site
    async with sm() as session:
        result = await session.execute(select(Organization).where(Organization.id == org_id))
        fetched_org = result.scalar_one()
        assert fetched_org.name == "Northern Border Command"

        site = Site(organization_id=fetched_org.id, name="Sector Alpha Post", timezone="Asia/Kolkata")
        session.add(site)
        await session.commit()
        site_id = site.id
        assert site_id is not None

    # 3. Add Camera and CredentialReference
    async with sm() as session:
        cam = Camera(
            site_id=site_id,
            name="Thermal-Cam-01",
            source_type="rtsp",
            endpoint="rtsp://192.168.1.100:554/live",
            protocol="rtsp",
            desired_state="ACTIVE",
            observed_state="IDLE",
            meta={"resolution": "1920x1080", "fps": 30, "codec": "h264"},
        )
        session.add(cam)
        await session.commit()
        cam_id = cam.id
        assert cam_id is not None

        cred = CredentialReference(
            camera_id=cam_id,
            username_enc="enc:admin",
            password_enc="enc:secret123",
        )
        session.add(cred)
        await session.commit()

    # 4. Query Camera with JSON metadata and update observed state
    async with sm() as session:
        res = await session.execute(select(Camera).where(Camera.id == cam_id))
        fetched_cam = res.scalar_one()
        assert fetched_cam.name == "Thermal-Cam-01"
        assert fetched_cam.meta is not None
        assert fetched_cam.meta.get("resolution") == "1920x1080"
        assert fetched_cam.meta.get("fps") == 30

        # Update observed state and meta
        fetched_cam.observed_state = "ACTIVE"
        fetched_cam.meta["night_vision"] = True
        await session.commit()

    # 5. Verify update persisted
    async with sm() as session:
        res = await session.execute(select(Camera).where(Camera.id == cam_id))
        updated_cam = res.scalar_one()
        assert updated_cam.observed_state == "ACTIVE"
        assert updated_cam.meta is not None
        assert updated_cam.meta.get("night_vision") is True


@pytest.mark.asyncio
async def test_live_db_outbox_operations(memory_db):
    sm = memory_db

    # Insert outbox records
    async with sm() as session:
        o1 = Outbox(
            topic="camera.event.created",
            payload={"event_id": "e-101", "type": "intrusion", "confidence": 0.94},
            status="pending",
            dedup_key="evt-101",
        )
        o2 = Outbox(
            topic="camera.heartbeat",
            payload={"camera_id": "cam-01", "uptime_s": 3600},
            status="pending",
            dedup_key="hb-01",
        )
        session.add_all([o1, o2])
        await session.commit()

    # Query outbox entries by topic and status
    async with sm() as session:
        res = await session.execute(select(Outbox).where(Outbox.topic == "camera.event.created"))
        entries = res.scalars().all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.dedup_key == "evt-101"
        assert entry.payload["type"] == "intrusion"
        assert entry.payload["confidence"] == 0.94

        # Update status to processed
        entry.status = "processed"
        await session.commit()

    # Verify status update
    async with sm() as session:
        res_pending = await session.execute(select(Outbox).where(Outbox.status == "pending"))
        pending = res_pending.scalars().all()
        assert len(pending) == 1
        assert pending[0].dedup_key == "hb-01"


@pytest.mark.asyncio
async def test_live_db_transaction_rollback(memory_db):
    sm = memory_db

    # Insert initial organization
    async with sm() as session:
        org = Organization(name="HQ Central")
        session.add(org)
        await session.commit()

    # Attempt to insert duplicate organization with unique constraint violation inside failed transaction
    with pytest.raises(IntegrityError):
        async with sm() as session:
            duplicate_org = Organization(name="HQ Central")
            session.add(duplicate_org)
            await session.flush()

    # Verify no corrupted records exist and session remained clean
    async with sm() as session:
        res = await session.execute(select(Organization))
        all_orgs = res.scalars().all()
        assert len(all_orgs) == 1
        assert all_orgs[0].name == "HQ Central"


@pytest.mark.asyncio
async def test_live_db_fastapi_dependency_generator():
    settings = Settings(db=DBConfig(url="sqlite+aiosqlite:///:memory:"))
    await dispose_engine()
    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Test happy path yielding session with commit
    async with contextlib.asynccontextmanager(get_session)() as session:
        org = Organization(name="Sector South")
        session.add(org)

    # Verify committed
    sm = get_sessionmaker()
    async with sm() as session:
        res = await session.execute(select(Organization).where(Organization.name == "Sector South"))
        org = res.scalar_one_or_none()
        assert org is not None
        assert org.name == "Sector South"

    # Test error path triggering rollback in get_session
    with pytest.raises(RuntimeError, match="Simulated route error"):
        async with contextlib.asynccontextmanager(get_session)() as session:
            org_dup = Organization(name="Sector South Duplicate")
            session.add(org_dup)
            raise RuntimeError("Simulated route error")

    # Verify the uncommitted org from error block was not persisted
    async with sm() as session:
        res = await session.execute(select(Organization).where(Organization.name == "Sector South Duplicate"))
        assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_live_db_file_based_sqlite(tmp_path: Path):
    db_file = tmp_path / "test_ibvap.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    settings = Settings(db=DBConfig(url=db_url))
    await dispose_engine()

    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        org = Organization(name="File DB Org")
        session.add(org)
        await session.commit()
        org_id = org.id

    await dispose_engine()

    # Reconnect to same file-based DB and verify data persisted
    new_sm = get_sessionmaker(settings)
    async with new_sm() as session:
        res = await session.execute(select(Organization).where(Organization.id == org_id))
        org = res.scalar_one()
        assert org.name == "File DB Org"

    await dispose_engine()


@pytest.mark.asyncio
async def test_live_db_all_models_persistence(memory_db):
    sm = memory_db
    async with sm() as session:
        org = Organization(name="Full Stack Org")
        session.add(org)
        await session.flush()

        site = Site(organization_id=org.id, name="Main Facility")
        session.add(site)
        await session.flush()

        cam = Camera(
            site_id=site.id,
            name="Dome-01",
            source_type="onvif",
            desired_state="ACTIVE",
            observed_state="ACTIVE",
        )
        session.add(cam)
        await session.flush()

        conn_test = ConnectionTest(
            camera_id=cam.id,
            endpoint="rtsp://10.0.0.5:554/stream1",
            protocol="rtsp",
            result="SUCCESS",
            reason_code=None,
            safe_message="Connected in 45ms",
            probe={"latency_ms": 45, "codecs": ["h264", "aac"]},
        )
        session.add(conn_test)

        sample = CameraHealthSample(
            camera_id=cam.id,
            stream_epoch=1,
            observed_state="ACTIVE",
            last_frame_age_ms=33,
            source_fps=30.0,
            analysis_fps=29.8,
            decode_errors=0,
            reconnect_count=0,
            queue_drops=0,
        )
        session.add(sample)
        await session.commit()

        test_id = conn_test.id
        sample_id = sample.id

    # Verify query
    async with sm() as session:
        res_test = await session.execute(select(ConnectionTest).where(ConnectionTest.id == test_id))
        t = res_test.scalar_one()
        assert t.safe_message == "Connected in 45ms"
        assert t.probe is not None
        assert t.probe.get("latency_ms") == 45

        res_sample = await session.execute(select(CameraHealthSample).where(CameraHealthSample.id == sample_id))
        s = res_sample.scalar_one()
        assert s.stream_epoch == 1
        assert s.analysis_fps == 29.8


@pytest.mark.asyncio
async def test_live_db_relationship_loading(memory_db):
    sm = memory_db
    async with sm() as session:
        org = Organization(name="Org with Relationships")
        session.add(org)
        await session.flush()

        site1 = Site(organization_id=org.id, name="North Gate")
        site2 = Site(organization_id=org.id, name="South Gate")
        session.add_all([site1, site2])
        await session.flush()

        cam1 = Camera(site_id=site1.id, name="Gate-Cam-1")
        cam2 = Camera(site_id=site1.id, name="Gate-Cam-2")
        session.add_all([cam1, cam2])
        await session.commit()
        site1_id = site1.id

    # Test loading site with relationship to cameras
    async with sm() as session:
        stmt = select(Site).where(Site.id == site1_id).options(selectinload(Site.cameras))
        res = await session.execute(stmt)
        loaded_site = res.scalar_one()
        assert len(loaded_site.cameras) == 2
        cam_names = {c.name for c in loaded_site.cameras}
        assert "Gate-Cam-1" in cam_names
        assert "Gate-Cam-2" in cam_names


def test_db_config_validation():
    from pydantic import ValidationError

    # Valid PostgreSQL URL
    cfg_pg = DBConfig(url="postgresql+asyncpg://ibvap:pass@localhost:5432/ibvap")
    assert cfg_pg.is_sqlite is False

    # Valid SQLite in-memory URL
    cfg_sqlite = DBConfig(url="sqlite+aiosqlite:///:memory:")
    assert cfg_sqlite.is_sqlite is True

    # Valid file-based SQLite URL
    cfg_file = DBConfig(url="sqlite+aiosqlite:///data/ibvap.db")
    assert cfg_file.is_sqlite is True

    # Invalid URL scheme
    with pytest.raises(ValidationError):
        DBConfig(url="mysql://user:pass@localhost/db")
