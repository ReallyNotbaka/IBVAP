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

from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from ibvap.api.app import create_app
from ibvap.config import DBConfig, Settings
from ibvap.db import dispose_engine, get_engine, get_sessionmaker
from ibvap.models import Base


@pytest.fixture(scope="session")
def shared_app():
    """Single FastAPI app instance shared by all API tests in the session."""
    return create_app()


@pytest.fixture()
def api_client(shared_app) -> Iterator[TestClient]:
    """Fresh TestClient per test bound to the session-shared app."""
    yield TestClient(shared_app)


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
