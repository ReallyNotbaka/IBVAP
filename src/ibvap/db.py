"""PostgreSQL and SQLite async engine + session factory - IBVAP durable store."""

from __future__ import annotations

import threading
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

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
                    poolclass=NullPool,
                    connect_args=connect_args,
                    echo=cfg.echo,
                    future=True,
                )
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
