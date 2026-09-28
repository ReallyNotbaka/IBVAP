"""Shared pytest fixtures and helpers — speed-optimised, semantics-preserving.

Goals:
- Build the FastAPI app once per session (``shared_app``) instead of once per
  test. Route state lives in module globals, so sharing the app object does not
  change test isolation; every test still gets a fresh ``TestClient``.
- Load the heavy ONNX detector once per test module (``shared_onnx_detector``)
  instead of once per test (~0.4-0.9s saved per construction).
- Replace fixed ``time.sleep`` polling with deadline-based ``wait_until``
  early-exit polling so wall-clock-heavy tests finish as soon as their
  condition is met (same deadlines and assertions as before).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.config import DBConfig, Settings
from ibvap.db import dispose_engine, get_engine, get_sessionmaker
from ibvap.models import Base

# Task 1 P0 fix-round 1: mutating routes are fail-closed, so every test runs
# with a configured token. api_client sends it by default (tests DO exercise
# the authenticated path); headerless clients must get 401 (see
# test_evidence_traversal_ssrf.py parametrized 401 test).
TEST_API_TOKEN = "ibvap-test-token-task1-p0"


@pytest.fixture(autouse=True)
def _test_api_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the API token for every test (auth reads env per request)."""
    monkeypatch.setenv("IBVAP_API_TOKEN", TEST_API_TOKEN)


@pytest.fixture(autouse=True)
def _isolate_route_state() -> Iterator[None]:
    """Snapshot/restore shared route globals around each test.

    ``shared_app`` is session-scoped, so the module-global camera registries
    (``SW._CAMERAS``/``SW._STATE_MACHINES``) and the in-memory outbox globals
    leak between tests without this guard. Snapshot before, restore after —
    every test observes the pre-test state and leaves no residue behind.

    Plain-data dicts (playback, observations, health, uploads, sites) are
    deep-copied. ``_ACTIVE_PIPELINES`` holds live ``MiniPipeline`` objects
    (ONNX sessions, locks — not deepcopyable), so only keys added during the
    test are removed. Watchlist/sightings singleton stores are NOT covered
    (follow-up): tests using them must clean up after themselves.
    """
    import copy

    from ibvap.api.routes import sites as _sites
    from ibvap.api.routes import uploads as _uploads
    from ibvap.events import outbox as _outbox
    from ibvap.services import stream_worker as SW

    cameras_snapshot = copy.deepcopy(SW._CAMERAS)
    machines_snapshot = copy.deepcopy(SW._STATE_MACHINES)
    playback_snapshot = copy.deepcopy(SW._PLAYBACK)
    observations_snapshot = copy.deepcopy(SW._OBSERVATIONS)
    health_snapshot = copy.deepcopy(SW._HEALTH)
    uploads_snapshot = copy.deepcopy(_uploads._UPLOADS)
    sites_snapshot = copy.deepcopy(_sites._SITES)
    pipelines_before = set(SW._ACTIVE_PIPELINES)
    with _outbox._LOCK:
        events_snapshot = copy.deepcopy(_outbox._EVENTS)
        outbox_snapshot = copy.deepcopy(_outbox._OUTBOX)
        dedup_event_snapshot = dict(_outbox._DEDUP_EVENT_INDEX)
        dedup_outbox_snapshot = dict(_outbox._DEDUP_OUTBOX_INDEX)
        outbox_id_snapshot = dict(_outbox._OUTBOX_ID_INDEX)
    try:
        yield
    finally:
        SW._CAMERAS.clear()
        SW._CAMERAS.update(cameras_snapshot)
        SW._STATE_MACHINES.clear()
        SW._STATE_MACHINES.update(machines_snapshot)
        SW._PLAYBACK.clear()
        SW._PLAYBACK.update(playback_snapshot)
        SW._OBSERVATIONS.clear()
        SW._OBSERVATIONS.update(observations_snapshot)
        SW._HEALTH.clear()
        SW._HEALTH.update(health_snapshot)
        _uploads._UPLOADS.clear()
        _uploads._UPLOADS.update(uploads_snapshot)
        _sites._SITES.clear()
        _sites._SITES.update(sites_snapshot)
        for added in set(SW._ACTIVE_PIPELINES) - pipelines_before:
            SW._ACTIVE_PIPELINES.pop(added, None)
        with _outbox._LOCK:
            _outbox._EVENTS.clear()
            _outbox._EVENTS.extend(events_snapshot)
            _outbox._OUTBOX.clear()
            _outbox._OUTBOX.extend(outbox_snapshot)
            _outbox._DEDUP_EVENT_INDEX.clear()
            _outbox._DEDUP_EVENT_INDEX.update(dedup_event_snapshot)
            _outbox._DEDUP_OUTBOX_INDEX.clear()
            _outbox._DEDUP_OUTBOX_INDEX.update(dedup_outbox_snapshot)
            _outbox._OUTBOX_ID_INDEX.clear()
            _outbox._OUTBOX_ID_INDEX.update(outbox_id_snapshot)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Explicit auth header for tests that build their own TestClient."""
    return {"X-API-Token": os.environ.get("IBVAP_API_TOKEN", TEST_API_TOKEN)}


@pytest.fixture(scope="session", autouse=True)
def _orderly_native_teardown() -> Iterator[None]:
    """Deterministic teardown before interpreter exit.

    Thread pools and DB engines torn down in a controlled order at session
    end instead of interpreter-finalization GC roulette, which has aborted
    (SIGABRT) teardown on Linux after an otherwise-green run. Sync on
    purpose: the asyncio runner is function-scoped, so a session async
    fixture is a ScopeMismatch.
    """
    yield
    from ibvap.core import evidence as _evidence

    _evidence.shutdown_evidence_executor()
    import asyncio
    import gc

    asyncio.run(dispose_engine())
    gc.collect()


@pytest.fixture(scope="session")
def shared_app():
    """Single FastAPI app instance shared by all API tests in the session."""
    return create_app()


@pytest.fixture()
def api_client(shared_app, auth_headers: dict[str, str]) -> Iterator[TestClient]:
    """Fresh TestClient per test bound to the session-shared app (authenticated)."""
    client = TestClient(shared_app)
    client.headers.update(auth_headers)
    yield client


@pytest.fixture(scope="module")
def shared_onnx_detector():
    """Module-scoped ONNX detector — loads model weights only once per module."""
    from ibvap.core.detector import ONNXDetectorProvider

    return ONNXDetectorProvider(model_path="models/yolo26n.onnx")


def wait_until(predicate: Callable[[], bool], timeout_s: float, interval_s: float = 0.05) -> bool:
    """Poll ``predicate`` until true or ``timeout_s`` elapses (monotonic clock).

    Returns True when the predicate held before the deadline, False on timeout.
    Callers keep their original assertion so test intent is unchanged.
    """
    import time

    deadline = time.monotonic() + timeout_s
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)


async def wait_until_async(predicate: Callable[[], bool], timeout_s: float, interval_s: float = 0.05) -> bool:
    """Async variant of :func:`wait_until` for asyncio tests."""
    import asyncio
    import time

    deadline = time.monotonic() + timeout_s
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(interval_s)


@pytest.fixture()
async def memory_db() -> AsyncIterator:
    """Yield a session factory bound to a fresh in-memory SQLite DB.

    Consolidates the per-test ``Settings`` + ``create_all`` + ``dispose_engine``
    boilerplate duplicated across DB tests.
    """
    settings = Settings(db=DBConfig(url="sqlite+aiosqlite:///:memory:"))
    await dispose_engine()
    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield get_sessionmaker(settings)
    finally:
        await dispose_engine()
