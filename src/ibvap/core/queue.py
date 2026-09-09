"""Bounded queues - spec 10."""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueMetrics:
    name: str
    max_size: int
    max_age_ms: int
    depth: int
    dropped: int
    warning_threshold: float = 0.8


class BoundedQueue:
    """Bounded latest-frame queue with drop-oldest-stale policy."""

    def __init__(self, name: str, max_size: int, max_age_ms: int = 400) -> None:
        self.name = name
        self.max_size = max_size
        self.max_age_ms = max_age_ms
        self._q: collections.deque[tuple[float, object]] = collections.deque()
        self.dropped = 0
        self.put_latency_ms: list[float] = []

    def put(self, item: object) -> bool:
        """Put item; drops oldest if full or stale. Returns True if enqueued."""
        now = time.monotonic() * 1000
        # drop stale in queue
        while self._q and (now - self._q[0][0]) > self.max_age_ms:
            self._q.popleft()
            self.dropped += 1
        if len(self._q) >= self.max_size:
            # drop oldest stale per spec: "drop oldest stale"
            self._q.popleft()
            self.dropped += 1
        self._q.append((now, item))
        return True

    def get_latest(self) -> object | None:
        """Get latest eligible frame, dropping stale."""
        if not self._q:
            return None
        now = time.monotonic() * 1000
        # Timestamps are non-decreasing, so a stale newest item means every
        # entry is stale: drop all at once (O(1)) instead of popping one by one.
        ts, item = self._q[-1]
        if (now - ts) > self.max_age_ms:
            self.dropped += len(self._q)
            self._q.clear()
            return None
        return item

    def get(self) -> object | None:
        if not self._q:
            return None
        _, item = self._q.popleft()
        return item

    @property
    def depth(self) -> int:
        return len(self._q)

    def metrics(self) -> QueueMetrics:
        return QueueMetrics(
            name=self.name,
            max_size=self.max_size,
            max_age_ms=self.max_age_ms,
            depth=self.depth,
            dropped=self.dropped,
        )
