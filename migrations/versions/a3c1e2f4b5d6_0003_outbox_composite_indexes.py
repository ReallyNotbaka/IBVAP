"""0003_outbox_composite_indexes - composite indexes for outbox querying

Revision ID: a3c1e2f4b5d6
Revises: f29b979f0e74
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3c1e2f4b5d6"
down_revision: str | None = "f29b979f0e74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_outbox_status_created_at", "outbox", ["status", "created_at"])
    op.create_index("ix_outbox_status_next_attempt", "outbox", ["status", "next_attempt_at"])
    op.create_index("ix_outbox_status_topic", "outbox", ["status", "topic"])


def downgrade() -> None:
    op.drop_index("ix_outbox_status_topic", table_name="outbox")
    op.drop_index("ix_outbox_status_next_attempt", table_name="outbox")
    op.drop_index("ix_outbox_status_created_at", table_name="outbox")
