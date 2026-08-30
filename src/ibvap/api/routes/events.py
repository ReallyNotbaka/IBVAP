"""Events timeline - Phase 3 slice."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ibvap.events.outbox import list_events, list_outbox

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("", response_model=list[dict[str, Any]])
async def get_events() -> list[dict[str, Any]]:
    return list_events()


@router.get("/outbox", response_model=list[dict[str, Any]])
async def get_outbox() -> list[dict[str, Any]]:
    return [{"id": o.id, "topic": o.topic, "status": o.status, "dedup_key": o.dedup_key} for o in list_outbox()]
