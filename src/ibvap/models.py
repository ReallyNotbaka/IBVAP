"""Typed SQLAlchemy 2 async models - minimal Phase 1 skeleton.

Spec 18 requires many entities; Phase 1 creates the foundation quartet:
organizations, sites, users, cameras. Full set added incrementally by migrations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_TYPE = MutableDict.as_mutable(JSON().with_variant(JSONB, "postgresql"))
UUID_TYPE = Uuid(as_uuid=True).with_variant(PG_UUID(as_uuid=True), "postgresql")


class Base(DeclarativeBase):
    pass


def _uuid7() -> uuid.UUID:
    # uuid7 available in Python 3.14+; fallback to uuid4 for 3.12
    uuid7_fn = getattr(uuid, "uuid7", None)
    if uuid7_fn is not None:
        try:
            return uuid7_fn()  # type: ignore[no-untyped-call]
        except Exception:
            pass
    # Fallback: uuid4 is sufficient for Phase 1 (unique, not strictly sortable)
    return uuid.uuid4()


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sites: Mapped[list[Site]] = relationship(back_populates="organization")


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="sites")
    cameras: Mapped[list[Camera]] = relationship(back_populates="site")

    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_site_org_name"),)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="smartphone_ip_webcam")
    # endpoint WITHOUT credentials - credentials via credential_references
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # stream epoch increments on every reconnect - tracker safety
    stream_epoch: Mapped[int] = mapped_column(default=0, nullable=False)
    desired_state: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    observed_state: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    site: Mapped[Site] = relationship(back_populates="cameras")

    __table_args__ = (
        Index("ix_cameras_site_id", "site_id"),
        UniqueConstraint("site_id", "name", name="uq_camera_site_name"),
    )


# PG outbox skeleton - full fields per ADR-0005 added in migration 0002
class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    dedup_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CredentialReference(Base):
    __tablename__ = "credential_references"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    username_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("camera_id", name="uq_cred_camera"),)


class ConnectionTest(Base):
    __tablename__ = "connection_tests"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    probe: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CameraHealthSample(Base):
    __tablename__ = "camera_health_samples"
    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=_uuid7)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    stream_epoch: Mapped[int] = mapped_column(nullable=False)
    observed_state: Mapped[str] = mapped_column(String(32), nullable=False)
    last_frame_age_ms: Mapped[int | None] = mapped_column(nullable=True)
    source_fps: Mapped[float | None] = mapped_column(nullable=True)
    analysis_fps: Mapped[float | None] = mapped_column(nullable=True)
    decode_errors: Mapped[int] = mapped_column(default=0, nullable=False)
    reconnect_count: Mapped[int] = mapped_column(default=0, nullable=False)
    queue_drops: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_health_camera_time", "camera_id", "created_at"),)
