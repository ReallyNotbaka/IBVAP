"""0002_phase2_credentials_health - credential refs, connection tests, health samples"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f29b979f0e74"
down_revision: str | None = "529855f7c518"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credential_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username_enc", sa.Text(), nullable=True),
        sa.Column("password_enc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("camera_id", name="uq_cred_camera"),
    )
    op.create_table(
        "connection_tests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("safe_message", sa.Text(), nullable=True),
        sa.Column("probe", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "camera_health_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stream_epoch", sa.Integer(), nullable=False),
        sa.Column("observed_state", sa.String(length=32), nullable=False),
        sa.Column("last_frame_age_ms", sa.Integer(), nullable=True),
        sa.Column("source_fps", sa.Float(), nullable=True),
        sa.Column("analysis_fps", sa.Float(), nullable=True),
        sa.Column("decode_errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reconnect_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queue_drops", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_health_camera_time", "camera_health_samples", ["camera_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_health_camera_time", table_name="camera_health_samples")
    op.drop_table("camera_health_samples")
    op.drop_table("connection_tests")
    op.drop_table("credential_references")
