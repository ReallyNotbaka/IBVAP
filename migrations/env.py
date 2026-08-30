"""Alembic env - supports both sync (psycopg) and async (asyncpg)."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

# ensure src on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ibvap.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # allow env override (tests set IBVAP_DB_URL)
    env_url = os.getenv("IBVAP_DB__URL") or os.getenv("DATABASE_URL")
    if env_url:
        # if caller passed asyncpg URL, downgrade to psycopg for alembic sync
        return env_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return str(config.get_main_option("sqlalchemy.url") or "")


def run_migrations_offline() -> None:
    url = _url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    connectable = create_engine(_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
