"""Task 2 P0 durability regressions (TDD RED first).

Covers: SQLite single-writer pool, URL-keyed engine cache, transactional
outbox save + restore with dedup indexes, no silent PG->SQLite fallback,
compose data volume + healthy postgres dependency, migration index parity.
"""

from __future__ import annotations

import pathlib
import re
import sys
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from ibvap import db as db_module
from ibvap.config import DBConfig, Settings
from ibvap.db import dispose_engine, get_engine, get_sessionmaker
from ibvap.events import outbox as outbox_module
from ibvap.models import Base
from ibvap.services import persistence as persistence_module


@pytest.fixture(autouse=True)
async def _isolate():
    outbox_module.clear_all()
    await dispose_engine()
    yield
    outbox_module.clear_all()
    await dispose_engine()


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


# --- SQLite single-writer pool ------------------------------------------------

_FALLBACK_SQLITE_URL = "sqlite+aiosqlite:///data/ibvap.db"


def test_sqlite_file_engine_uses_staticpool() -> None:
    eng = db_module.get_engine_for_url(_FALLBACK_SQLITE_URL)
    assert type(eng.pool).__name__ == "StaticPool"


def test_sqlite_memory_engine_uses_staticpool() -> None:
    eng = db_module.get_engine_for_url("sqlite+aiosqlite:///:memory:")
    assert type(eng.pool).__name__ == "StaticPool"


def test_get_engine_file_sqlite_uses_staticpool(tmp_path) -> None:
    settings = Settings(db=DBConfig(url=f"sqlite+aiosqlite:///{(tmp_path / 'f.db').as_posix()}"))
    eng = get_engine(settings)
    assert type(eng.pool).__name__ == "StaticPool"


# --- URL-keyed engine cache ---------------------------------------------------


def test_engine_cache_keyed_by_url() -> None:
    a1 = db_module.get_engine_for_url("sqlite+aiosqlite:///:memory:")
    a2 = db_module.get_engine_for_url("sqlite+aiosqlite:///:memory:")
    b = db_module.get_engine_for_url(_FALLBACK_SQLITE_URL)
    assert a1 is a2
    assert a1 is not b


def test_get_engine_delegates_to_url_cache(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'g.db').as_posix()}"
    settings = Settings(db=DBConfig(url=url))
    assert get_engine(settings) is db_module.get_engine_for_url(url)


def test_sessionmaker_bound_to_cached_engine(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 's.db').as_posix()}"
    settings = Settings(db=DBConfig(url=url))
    sm1 = get_sessionmaker(settings)
    sm2 = get_sessionmaker(settings)
    assert sm1 is sm2
    assert sm1.kw["bind"] is db_module.get_engine_for_url(url)


# --- Transactional outbox -----------------------------------------------------

_SENTINEL_DEDUP = "durability-dedup-1"


@pytest.mark.asyncio
async def test_save_event_with_outbox_survives_restore(tmp_path) -> None:
    db_file = tmp_path / "outbox_survives.db"
    settings = Settings(db=DBConfig(url=f"sqlite+aiosqlite:///{db_file.as_posix()}"))
    await persistence_module.init_persistence(settings)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        eid = await persistence_module.save_event_with_outbox(
            session,
            {"camera_id": "cam-1", "event_type": "watchlist_hit"},
            dedup_key=_SENTINEL_DEDUP,
        )
        await session.commit()

    # In-mem entry id must equal the returned (DB row) id so mark_delivered works.
    assert eid in outbox_module._OUTBOX_ID_INDEX
    outbox_module.mark_delivered(eid)
    assert outbox_module._OUTBOX_ID_INDEX[eid].status == "done"

    # Simulate process restart: drop all in-memory state, restore from DB.
    outbox_module.clear_all()
    assert outbox_module.list_events() == []
    await persistence_module.init_persistence(settings)

    assert any(e.get("id") == eid for e in outbox_module.list_events())
    assert _SENTINEL_DEDUP in outbox_module._DEDUP_OUTBOX_INDEX
    assert _SENTINEL_DEDUP in outbox_module._DEDUP_EVENT_INDEX
    assert eid in outbox_module._OUTBOX_ID_INDEX
    # Ids stable across restart: mark_delivered works on the restored entry too.
    outbox_module.mark_delivered(eid)
    assert outbox_module._OUTBOX_ID_INDEX[eid].status == "done"


@pytest.mark.asyncio
async def test_save_event_with_outbox_defers_commit(tmp_path) -> None:
    from ibvap.models import Outbox as DBOutbox

    db_file = tmp_path / "outbox_defer.db"
    settings = Settings(db=DBConfig(url=f"sqlite+aiosqlite:///{db_file.as_posix()}"))
    await persistence_module.init_persistence(settings)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        await persistence_module.save_event_with_outbox(session, {"camera_id": "cam-9"}, dedup_key="defer-dedup-1")
        await session.rollback()  # caller decides; function must NOT have committed

    # Rollback discards both the row AND the deferred in-mem mirror: no phantoms.
    assert "defer-dedup-1" not in outbox_module._DEDUP_OUTBOX_INDEX
    assert "defer-dedup-1" not in outbox_module._DEDUP_EVENT_INDEX
    assert all(e.get("dedup_key") != "defer-dedup-1" for e in outbox_module.list_events())

    async with sm() as session:
        res = await session.execute(select(DBOutbox).where(DBOutbox.dedup_key == "defer-dedup-1"))
        assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_save_event_with_outbox_dedup_idempotent(tmp_path) -> None:
    from ibvap.models import Outbox as DBOutbox

    db_file = tmp_path / "outbox_dupe.db"
    settings = Settings(db=DBConfig(url=f"sqlite+aiosqlite:///{db_file.as_posix()}"))
    await persistence_module.init_persistence(settings)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        eid1 = await persistence_module.save_event_with_outbox(
            session, {"camera_id": "c", "seq": 1}, dedup_key="dupe-1"
        )
        eid2 = await persistence_module.save_event_with_outbox(
            session, {"camera_id": "c", "seq": 2}, dedup_key="dupe-1"
        )
        assert eid1 == eid2
        await session.commit()

    async with sm() as session:
        res = await session.execute(select(DBOutbox).where(DBOutbox.dedup_key == "dupe-1"))
        assert len(res.scalars().all()) == 1


# --- Silent fallback ----------------------------------------------------------

_BAD_PG_URL = "postgresql+asyncpg://ibvap:ibvap@127.0.0.1:1/ibvap"


@pytest.mark.asyncio
async def test_no_silent_pg_fallback_without_flag(monkeypatch) -> None:
    monkeypatch.delenv("IBVAP_DB__ALLOW_SQLITE_FALLBACK", raising=False)
    settings = Settings(db=DBConfig(url=_BAD_PG_URL))
    with pytest.raises((DBAPIError, OSError)):
        await db_module.init_db(settings)


@pytest.mark.asyncio
async def test_sqlite_fallback_allowed_with_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IBVAP_DB__ALLOW_SQLITE_FALLBACK", "1")
    monkeypatch.chdir(tmp_path)
    settings = Settings(db=DBConfig(url=_BAD_PG_URL))
    assert await db_module.init_db(settings) is True
    assert (tmp_path / "data" / "ibvap.db").exists()
    # Single-writer invariant: no-arg resolution after fallback must return the
    # SAME engine object (absolute fallback URL), not create a second engine.
    # NOTE: get_engine() must run FIRST — a get_engine_for_url() hit would
    # re-stick the ambient URL and mask a stale _CURRENT_URL.
    _, fallback_url = db_module._fallback_sqlite_url(settings)
    assert get_engine() is db_module.get_engine_for_url(fallback_url)
    assert get_sessionmaker().kw["bind"] is db_module.get_engine_for_url(fallback_url)
    assert get_engine(settings) is db_module.get_engine_for_url(fallback_url)


def test_fallback_sqlite_url_resolves_absolute(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    path, url = db_module._fallback_sqlite_url(None)
    assert pathlib.Path(path).is_absolute()
    assert pathlib.Path(path) == tmp_path / "data" / "ibvap.db"
    assert url == f"sqlite+aiosqlite:///{(tmp_path / 'data' / 'ibvap.db').as_posix()}"


# --- Compose durability -------------------------------------------------------


def test_compose_app_volume_and_depends_on() -> None:
    import yaml

    compose = yaml.safe_load((_repo_root() / "compose.yaml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]
    assert "./data:/app/data" in app["volumes"]
    assert app["depends_on"]["postgres"]["condition"] == "service_healthy"
    # The app only reads IBVAP_* env: without IBVAP_DB__URL it fail-closes to localhost.
    assert app["environment"]["IBVAP_DB__URL"] == "postgresql+asyncpg://ibvap:ibvap@postgres:5432/ibvap"


# --- Migration parity ---------------------------------------------------------


def _migration_index_names() -> list[str]:
    names: list[str] = []
    for path in sorted((_repo_root() / "migrations" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        names.extend(re.findall(r"create_index\(\s*[\"']([^\"']+)[\"']", text))
    return names


def test_migration_no_duplicate_index_names() -> None:
    names = _migration_index_names()
    assert len(names) == len(set(names)), f"duplicate create_index: {sorted(names)}"


def test_migration_index_parity_with_metadata() -> None:
    meta_names = {idx.name for table in Base.metadata.tables.values() for idx in table.indexes}
    assert set(_migration_index_names()) == meta_names


def test_upgrade_head_on_fresh_sqlite(tmp_path) -> None:
    import subprocess

    db_file = tmp_path / "mig_head.db"
    env = {
        **dict(__import__("os").environ),
        "IBVAP_DB__URL": f"sqlite:///{db_file.as_posix()}",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]

    from sqlalchemy import create_engine, inspect

    insp = inspect(create_engine(f"sqlite:///{db_file.as_posix()}"))
    assert {"organizations", "sites", "cameras", "outbox"} <= set(insp.get_table_names())
    assert str(uuid.uuid4())  # keep uuid import live if trimmed later
