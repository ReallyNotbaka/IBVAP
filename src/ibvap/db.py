"""PostgreSQL and SQLite async engine + session factory - IBVAP durable store."""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, StaticPool

from ibvap.config import Settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_engine_lock = threading.Lock()
_sessionmaker_lock = threading.Lock()


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        # Double-checked locking for thread-safe singleton init.
        if _engine is not None:
            return _engine
        cfg = (settings or Settings()).db
        if "sqlite" in cfg.url:
            connect_args = {"check_same_thread": False}
            if ":memory:" in cfg.url or "mode=memory" in cfg.url:
                _engine = create_async_engine(
                    cfg.url,
                    poolclass=StaticPool,
                    connect_args=connect_args,
                    echo=cfg.echo,
                    future=True,
                )
            else:
                _engine = create_async_engine(
                    cfg.url,
                    poolclass=AsyncAdaptedQueuePool,
                    pool_size=cfg.pool_size,
                    max_overflow=cfg.max_overflow,
                    connect_args=connect_args,
                    echo=cfg.echo,
                    future=True,
                )

            @event.listens_for(_engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.execute("PRAGMA cache_size=-64000")
                    cursor.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    pass
                finally:
                    cursor.close()
        else:
            _engine = create_async_engine(
                cfg.url,
                pool_size=cfg.pool_size,
                max_overflow=cfg.max_overflow,
                echo=cfg.echo,
                future=True,
            )
        return _engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is not None:
        return _sessionmaker
    with _sessionmaker_lock:
        # Double-checked locking for thread-safe singleton init.
        if _sessionmaker is not None:
            return _sessionmaker
        engine = get_engine(settings)
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        return _sessionmaker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency - yields one session per request."""
    sm = get_sessionmaker()
    # `async with` already closes the session; do not close explicitly (avoids double-close).
    async with sm() as session:
        try:
            yield session
            # Skip commit roundtrip for read-only requests (no pending writes).
            if session.new or session.dirty or session.deleted:
                await session.commit()
            else:
                await session.rollback()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    with _engine_lock:
        engine = _engine
        _engine = None
        _sessionmaker = None
    if engine is not None:
        await engine.dispose()


async def init_db(settings: Settings | None = None) -> bool:
    """Initialize database tables with automatic SQLite WAL fallback if primary DB is unavailable."""
    global _engine, _sessionmaker
    from pathlib import Path

    import structlog

    from ibvap.models import Base

    logger = structlog.get_logger("ibvap.db")
    engine = get_engine(settings)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return True
    except Exception as e:
        logger.warning(
            "db_primary_unavailable",
            error=str(e),
            msg="Configured primary database unavailable; falling back to durable SQLite store",
        )
        with _engine_lock:
            if _engine is not None:
                import contextlib

                with contextlib.suppress(Exception):
                    await _engine.dispose()
                _engine = None
                _sessionmaker = None

            Path("data").mkdir(parents=True, exist_ok=True)
            sqlite_url = "sqlite+aiosqlite:///data/ibvap.db"
            connect_args = {"check_same_thread": False}
            _engine = create_async_engine(
                sqlite_url,
                poolclass=AsyncAdaptedQueuePool,
                connect_args=connect_args,
                echo=False,
                future=True,
            )

            @event.listens_for(_engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.execute("PRAGMA cache_size=-64000")
                    cursor.execute("PRAGMA foreign_keys=ON")
                except Exception:
                    pass
                finally:
                    cursor.close()

            _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)

        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("db_sqlite_fallback_ready", db_path="data/ibvap.db")
        return True

