from __future__ import annotations

import time

from ibvap.core.queue import BoundedQueue


def test_bounded_queue_drop_oldest() -> None:
    q = BoundedQueue("test", max_size=2, max_age_ms=400)
    q.put("a")
    q.put("b")
    assert q.depth == 2
    q.put("c")  # should drop a
    assert q.depth == 2
    assert q.dropped >= 1
    assert q.get() == "b"
    assert q.get() == "c"


def test_bounded_queue_max_age_drop() -> None:
    q = BoundedQueue("test2", max_size=10, max_age_ms=10)
    q.put("old")
    time.sleep(0.02)
    q.put("new")
    # old should be considered stale when getting latest
    latest = q.get_latest()
    assert latest == "new"
