"""Transactional outbox - in-mem Phase 3 slice.

Production uses PostgreSQL table `outbox` with FOR UPDATE SKIP LOCKED polling (ADR-0005).
Phase 3 slice uses in-mem list but preserves same API: atomic write of event+outbox.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OutboxEntry:
    id: str
    topic: str
    payload: dict[str, Any]
    dedup_key: str | None
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


_OUTBOX: list[OutboxEntry] = []
_EVENTS: list[dict[str, Any]] = []
# O(1) indexes to avoid O(n) scans per write/deliver on large streams.
_DEDUP_EVENT_INDEX: dict[str, dict[str, Any]] = {}
_DEDUP_OUTBOX_INDEX: dict[str, OutboxEntry] = {}
_OUTBOX_ID_INDEX: dict[str, OutboxEntry] = {}


def transactional_write(
    event: dict[str, Any],
    dedup_key: str | None = None,
    topics: tuple[str, ...] = ("event.created",),
) -> OutboxEntry:
    """Simulate single PG transaction writing event + outbox. Idempotent via dedup_key."""
    if dedup_key:
        existing = _DEDUP_OUTBOX_INDEX.get(dedup_key)
        if existing is not None and _DEDUP_EVENT_INDEX.get(dedup_key) is not None:
            return existing
    eid = str(uuid.uuid4())
    event["id"] = eid
    event["dedup_key"] = dedup_key
    event["created_at"] = time.time()
    _EVENTS.append(event)
    entry = OutboxEntry(id=str(uuid.uuid4()), topic=topics[0], payload=event, dedup_key=dedup_key)
    _OUTBOX.append(entry)
    _OUTBOX_ID_INDEX[entry.id] = entry
    if dedup_key:
        _DEDUP_EVENT_INDEX[dedup_key] = event
        _DEDUP_OUTBOX_INDEX[dedup_key] = entry
    return entry


def list_events() -> list[dict[str, Any]]:
    return list(_EVENTS)


def list_outbox(status: str | None = None) -> list[OutboxEntry]:
    if status:
        return [o for o in _OUTBOX if o.status == status]
    return list(_OUTBOX)


def mark_delivered(outbox_id: str) -> None:
    entry = _OUTBOX_ID_INDEX.get(outbox_id)
    if entry is not None:
        entry.status = "done"
        return
    for o in _OUTBOX:
        if o.id == outbox_id:
            o.status = "done"
            _OUTBOX_ID_INDEX[outbox_id] = o
            break


def clear_events() -> int:
    count = len(_EVENTS)
    _EVENTS.clear()
    _DEDUP_EVENT_INDEX.clear()
    return count


def clear_all() -> None:
    _EVENTS.clear()
    _OUTBOX.clear()
    _DEDUP_EVENT_INDEX.clear()
    _DEDUP_OUTBOX_INDEX.clear()
    _OUTBOX_ID_INDEX.clear()
