"""PostgreSQL and SQLite async engine + session factory - IBVAP durable store."""

from __future__ import annotations

import contextlib
import os
import re
import threading
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from ibvap.config import Settings

# URL-keyed caches: one engine/sessionmaker per DB URL. The most recently
# resolved URL also becomes the ambient default, so legacy no-arg callers
# (get_session(), persistence helpers, older tests) keep working untouched.
_ENGINES: dict[str, AsyncEngine] = {}
_SESSIONMAKERS: dict[str, async_sessionmaker[AsyncSession]] = {}
_engine_lock = threading.Lock()
_CURRENT_URL: str | None = None

_SQLITE_FALLBACK_TRUE_VALUES = {"1", "true", "yes", "on"}


def sqlite_fallback_allowed() -> bool:
    """Explicit opt-in for PG -> SQLite fallback (fail-closed by default)."""
    return os.getenv("IBVAP_DB__ALLOW_SQLITE_FALLBACK", "").strip().lower() in _SQLITE_FALLBACK_TRUE_VALUES


def _is_sqlite_url(url: str) -> bool:
    """Strict SQLite URL check (prefix match, not substring)."""
    return url.startswith(("sqlite://", "sqlite+aiosqlite://"))


def _redact_url(url: str) -> str:
    """Strip credentials for logs (global constraint: never log secrets)."""
    return re.sub(r"(://[^/]*?):[^/]*?@", r"\1:***@", url)


def _fallback_sqlite_url(settings: Settings | None = None) -> tuple[str, str]:
    """Resolve the fallback SQLite file against the configured data dir (absolute).

    Never CWD-dependent: a relative ``data_dir`` is anchored at the process
    working directory at call time and returned as an absolute path + URL.
    """
    from pathlib import Path

    data_dir = Path((settings or Settings()).app.data_dir)
    if not data_dir.is_absolute():
        data_dir = Path.cwd() / data_dir
    db_path = data_dir / "ibvap.db"
    return db_path.as_posix(), f"sqlite+aiosqlite:///{db_path.as_posix()}"


def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
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


def get_engine_for_url(
    url: str,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 10,
) -> AsyncEngine:
    """Return the cached engine for ``url``, creating it on first use.

    All SQLite (file and memory) uses ``StaticPool``: a single serialized
    writer, which avoids SQLITE_BUSY under concurrent async tasks. PostgreSQL
    keeps a sized QueuePool. The resolved URL becomes the ambient default for
    no-arg :func:`get_engine` / :func:`get_sessionmaker` callers.

    ``echo``/``pool_size``/``max_overflow`` apply at creation only; a cache
    hit returns the existing engine unchanged.
    """
    global _CURRENT_URL
    cached = _ENGINES.get(url)
    if cached is not None:
        with _engine_lock:
            _CURRENT_URL = url
        return cached
    with _engine_lock:
        cached = _ENGINES.get(url)
        if cached is not None:
            _CURRENT_URL = url
            return cached
        if _is_sqlite_url(url):
            engine = create_async_engine(
                url,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
                echo=echo,
                future=True,
            )
            event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)
        else:
            engine = create_async_engine(
                url,
                pool_size=pool_size,
                max_overflow=max_overflow,
                echo=echo,
                future=True,
            )
        _ENGINES[url] = engine
        _CURRENT_URL = url
        return engine


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    if settings is not None:
        cfg = settings.db
        return get_engine_for_url(cfg.url, echo=cfg.echo, pool_size=cfg.pool_size, max_overflow=cfg.max_overflow)
    with _engine_lock:
        current = _CURRENT_URL
    if current is not None:
        return get_engine_for_url(current)
    cfg = Settings().db
    return get_engine_for_url(cfg.url, echo=cfg.echo, pool_size=cfg.pool_size, max_overflow=cfg.max_overflow)


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    if settings is not None:
        key = settings.db.url
        engine = get_engine(settings)
    else:
        with _engine_lock:
            current = _CURRENT_URL
        if current is not None:
            key = current
            engine = get_engine_for_url(current)
        else:
            cfg = Settings().db
            key = cfg.url
            engine = get_engine_for_url(cfg.url, echo=cfg.echo, pool_size=cfg.pool_size, max_overflow=cfg.max_overflow)
    cached = _SESSIONMAKERS.get(key)
    if cached is not None:
        return cached
    with _engine_lock:
        cached = _SESSIONMAKERS.get(key)
        if cached is None:
            cached = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            _SESSIONMAKERS[key] = cached
        return cached


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
    global _CURRENT_URL
    # Snapshot under lock; dispose outside (never await inside threading.Lock).
    with _engine_lock:
        engines = list(_ENGINES.values())
        _ENGINES.clear()
        _SESSIONMAKERS.clear()
        _CURRENT_URL = None
    seen: set[int] = set()
    for engine in engines:
        if id(engine) in seen:
            continue  # fallback aliasing can store one engine under two keys
        seen.add(id(engine))
        await engine.dispose()


async def init_db(settings: Settings | None = None) -> bool:
    """Initialize database tables.

    Falls back to the durable SQLite store ONLY when the configured URL is
    already SQLite or ``IBVAP_DB__ALLOW_SQLITE_FALLBACK=1``; otherwise the
    primary error is re-raised (fail-closed, no silent split-brain).
    """
    global _CURRENT_URL
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
        if settings is not None:
            cfg_url = settings.db.url
        else:
            with _engine_lock:
                cfg_url = _CURRENT_URL or Settings().db.url
        if not _is_sqlite_url(cfg_url) and not sqlite_fallback_allowed():
            logger.error("db_primary_unavailable_no_fallback", error=str(e), db_url=_redact_url(cfg_url))
            raise
        logger.warning(
            "db_primary_unavailable",
            error=str(e),
            db_url=_redact_url(cfg_url),
            msg="Configured primary database unavailable; falling back to durable SQLite store",
        )
        # Snapshot under lock; dispose outside (never await inside threading.Lock).
        with _engine_lock:
            old = _ENGINES.pop(cfg_url, None)
            _SESSIONMAKERS.pop(cfg_url, None)
        if old is not None:
            with contextlib.suppress(Exception):
                await old.dispose()

        fallback_path, fallback_url = _fallback_sqlite_url(settings)
        Path(fallback_path).parent.mkdir(parents=True, exist_ok=True)
        fallback = get_engine_for_url(fallback_url)
        # Alias the configured URL to the fallback so existing callers that
        # hold PG settings transparently use the SQLite store afterwards.
        with _engine_lock:
            _ENGINES[cfg_url] = fallback
            sm = _SESSIONMAKERS.get(fallback_url)
            if sm is None:
                sm = async_sessionmaker(fallback, expire_on_commit=False, class_=AsyncSession)
                _SESSIONMAKERS[fallback_url] = sm
            _SESSIONMAKERS[cfg_url] = sm
            _CURRENT_URL = fallback_url

        async with fallback.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("db_sqlite_fallback_ready", db_path=fallback_path)
        return True
