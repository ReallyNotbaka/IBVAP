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


def transactional_write(
    event: dict[str, Any],
    dedup_key: str | None = None,
    topics: tuple[str, ...] = ("event.created",),
) -> OutboxEntry:
    """Simulate single PG transaction writing event + outbox. Idempotent via dedup_key."""
    if dedup_key:
        for e in _EVENTS:
            if e.get("dedup_key") == dedup_key:
                # already exists - return existing outbox
                for o in _OUTBOX:
                    if o.dedup_key == dedup_key:
                        return o
    eid = str(uuid.uuid4())
    event["id"] = eid
    event["dedup_key"] = dedup_key
    event["created_at"] = time.time()
    _EVENTS.append(event)
    entry = OutboxEntry(id=str(uuid.uuid4()), topic=topics[0], payload=event, dedup_key=dedup_key)
    _OUTBOX.append(entry)
    return entry


def list_events() -> list[dict[str, Any]]:
    return list(_EVENTS)


def list_outbox(status: str | None = None) -> list[OutboxEntry]:
    if status:
        return [o for o in _OUTBOX if o.status == status]
    return list(_OUTBOX)


def mark_delivered(outbox_id: str) -> None:
    for o in _OUTBOX:
        if o.id == outbox_id:
            o.status = "done"
            break


def clear_all() -> None:
    _EVENTS.clear()
    _OUTBOX.clear()
