"""Persistence service for IBVAP cameras, zones, and security events.

Bridges the in-memory streaming context with durable database storage
(PostgreSQL or SQLite WAL fallback), ensuring cameras, fences, and
timeline alerts survive application and service restarts.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from sqlalchemy import delete, select

from ibvap.config import Settings
from ibvap.core.camera_state import CameraState, CameraStateMachine
from ibvap.db import get_sessionmaker, init_db
from ibvap.events.outbox import _EVENTS, _OUTBOX, OutboxEntry
from ibvap.events.outbox import _LOCK as OUTBOX_LOCK
from ibvap.models import Camera as DBCamera
from ibvap.models import Organization, Site
from ibvap.models import Outbox as DBOutbox
from ibvap.services.stream_worker import (
    _CAMERAS,
    _PLAYBACK,
    _STATE_MACHINES,
    _start_camera_worker,
)

logger = structlog.get_logger(__name__)

DEFAULT_SITE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def ensure_default_hierarchy() -> uuid.UUID:
    """Ensure at least one Organization and Site exists for foreign keys."""
    sm = get_sessionmaker()
    async with sm() as session:
        # Check if default site exists
        res = await session.execute(select(Site).where(Site.id == DEFAULT_SITE_ID))
        site = res.scalar_one_or_none()
        if site is not None:
            return site.id

        # Check or create default Organization
        org_res = await session.execute(select(Organization).limit(1))
        org = org_res.scalar_one_or_none()
        if org is None:
            org = Organization(name="Default Border Command")
            session.add(org)
            await session.flush()

        # Create default Site with deterministic UUID
        new_site = Site(
            id=DEFAULT_SITE_ID,
            organization_id=org.id,
            name="Default Operational Post",
            timezone="UTC",
        )
        session.add(new_site)
        try:
            await session.commit()
            return new_site.id
        except Exception:
            await session.rollback()
            return DEFAULT_SITE_ID


async def save_camera_to_db(cam_data: dict[str, Any]) -> None:
    """Persist or update camera metadata in the database."""
    try:
        raw_id = cam_data.get("id")
        if not raw_id:
            return
        try:
            cam_uuid = uuid.UUID(str(raw_id))
        except (ValueError, TypeError):
            cam_uuid = uuid.uuid4()

        raw_site = cam_data.get("site_id")
        try:
            site_uuid = uuid.UUID(str(raw_site)) if raw_site else DEFAULT_SITE_ID
        except (ValueError, TypeError):
            site_uuid = DEFAULT_SITE_ID

        meta = {
            "fence": cam_data.get("fence"),
            "zones": cam_data.get("zones"),
            "temporary": cam_data.get("temporary", False),
            "site_cidr_allowlist": cam_data.get("_site_cidr_allowlist"),
        }

        sm = get_sessionmaker()
        async with sm() as session:
            # Check if camera exists
            res = await session.execute(select(DBCamera).where(DBCamera.id == cam_uuid))
            existing = res.scalar_one_or_none()

            if existing is not None:
                existing.name = str(cam_data.get("name", existing.name))
                existing.source_type = str(cam_data.get("source_type", existing.source_type))
                existing.endpoint = str(cam_data.get("endpoint", existing.endpoint))
                existing.protocol = str(cam_data.get("protocol", existing.protocol))
                existing.desired_state = str(cam_data.get("desired_state", existing.desired_state))
                existing.observed_state = str(cam_data.get("observed_state", existing.observed_state))
                existing.meta = meta
            else:
                new_cam = DBCamera(
                    id=cam_uuid,
                    site_id=site_uuid,
                    name=str(cam_data.get("name", "Camera")),
                    source_type=str(cam_data.get("source_type", "smartphone_ip_webcam")),
                    endpoint=str(cam_data.get("endpoint", "")),
                    protocol=str(cam_data.get("protocol", "http")),
                    stream_epoch=int(cam_data.get("stream_epoch", 0)),
                    desired_state=str(cam_data.get("desired_state", "STREAMING")),
                    observed_state=str(cam_data.get("observed_state", "STREAMING")),
                    meta=meta,
                )
                session.add(new_cam)

            await session.commit()
            logger.debug("camera_saved_to_db", camera_id=str(cam_uuid))
    except Exception as e:
        logger.warning("save_camera_to_db_error", error=str(e), camera_id=cam_data.get("id"))


async def delete_camera_from_db(camera_id: str) -> None:
    """Remove camera record from database."""
    try:
        try:
            cam_uuid = uuid.UUID(camera_id)
        except (ValueError, TypeError):
            return

        sm = get_sessionmaker()
        async with sm() as session:
            await session.execute(delete(DBCamera).where(DBCamera.id == cam_uuid))
            await session.commit()
            logger.debug("camera_deleted_from_db", camera_id=camera_id)
    except Exception as e:
        logger.warning("delete_camera_from_db_error", error=str(e), camera_id=camera_id)


async def save_outbox_event_to_db(entry: OutboxEntry) -> None:
    """Persist an outbox event into the durable database."""
    try:
        try:
            evt_uuid = uuid.UUID(entry.id)
        except (ValueError, TypeError):
            evt_uuid = uuid.uuid4()

        sm = get_sessionmaker()
        async with sm() as session:
            db_outbox = DBOutbox(
                id=evt_uuid,
                topic=entry.topic,
                payload=entry.payload,
                status=entry.status,
                dedup_key=entry.dedup_key,
            )
            session.add(db_outbox)
            await session.commit()
    except Exception as e:
        logger.warning("save_outbox_event_error", error=str(e), event_id=entry.id)


async def init_persistence(settings: Settings | None = None) -> None:
    """Boot up database persistence, verify schema, and restore active entities."""
    try:
        db_ready = await init_db(settings)
        if not db_ready:
            logger.warning("persistence_init_skipped", reason="db_init_failed")
            return

        await ensure_default_hierarchy()

        # 1. Restore Cameras
        sm = get_sessionmaker()
        async with sm() as session:
            res = await session.execute(select(DBCamera))
            saved_cameras = res.scalars().all()

            for cam in saved_cameras:
                cam_id = str(cam.id)
                if cam_id in _CAMERAS:
                    continue  # already loaded

                meta = cam.meta or {}
                if meta.get("temporary"):
                    continue  # skip temporary camera test feeds

                cam_data: dict[str, Any] = {
                    "id": cam_id,
                    "name": cam.name,
                    "site_id": str(cam.site_id),
                    "source_type": cam.source_type,
                    "endpoint": cam.endpoint,
                    "protocol": cam.protocol,
                    "stream_epoch": cam.stream_epoch,
                    "desired_state": cam.desired_state,
                    "observed_state": cam.observed_state,
                    "has_credentials": False,
                    "temporary": False,
                    "created_at": cam.created_at.timestamp() if cam.created_at else time.time(),
                }

                if meta.get("fence"):
                    cam_data["fence"] = meta["fence"]
                if meta.get("zones"):
                    cam_data["zones"] = meta["zones"]

                _CAMERAS[cam_id] = cam_data

                # Initialize State Machine
                cam_sm = CameraStateMachine(camera_id=cam_id)
                if cam.desired_state == "DISABLED":
                    cam_sm.disable()
                else:
                    cam_sm.transition(CameraState.VALIDATING, reason="restored_from_db", safe_message="Validating")
                    cam_sm.transition(CameraState.SAVING, reason="restored_from_db", safe_message="Saving")
                    cam_sm.transition(CameraState.STARTING, reason="restored_from_db", safe_message="Restored")
                    cam_sm.transition(CameraState.STREAMING, reason="restored_from_db", safe_message="Streaming")
                _STATE_MACHINES[cam_id] = cam_sm

                # Initialize playback if file camera
                if cam.source_type == "video_footage":
                    _PLAYBACK[cam_id] = {
                        "state": "playing",
                        "position_seconds": 0.0,
                        "duration_seconds": None,
                        "fps": None,
                    }

                # Start worker if not disabled and not synthetic
                if cam.desired_state != "DISABLED" and not (cam.endpoint and cam.endpoint.startswith("synthetic://")):
                    _start_camera_worker(cam_id)

            logger.info("cameras_restored_from_db", count=len(saved_cameras))

            # 2. Restore recent events to timeline (up to 500)
            ev_res = await session.execute(
                select(DBOutbox).order_by(DBOutbox.created_at.desc()).limit(500)
            )
            saved_events = ev_res.scalars().all()

            with OUTBOX_LOCK:
                existing_ids = {e.get("id") for e in _EVENTS if e.get("id")}
                # Reverse to append oldest first
                for se in reversed(saved_events):
                    if str(se.id) not in existing_ids and isinstance(se.payload, dict):
                        _EVENTS.append(se.payload)
                        outbox_ent = OutboxEntry(
                            id=str(se.id),
                            topic=se.topic,
                            payload=se.payload,
                            dedup_key=se.dedup_key,
                            status=se.status,
                            created_at=se.created_at.timestamp() if se.created_at else time.time(),
                        )
                        _OUTBOX.append(outbox_ent)
                        existing_ids.add(str(se.id))

            logger.info("events_restored_from_db", count=len(saved_events))

    except Exception as e:
        logger.error("persistence_initialization_error", error=str(e))
