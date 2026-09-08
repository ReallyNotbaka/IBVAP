"""Events timeline - Phase 3 slice."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ibvap.events.outbox import clear_events, list_events, list_outbox

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _parse_timestamp(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            try:
                from datetime import datetime
                return datetime.fromisoformat(val).timestamp()
            except Exception:
                return 0.0
    return 0.0


@router.get("", response_model=list[dict[str, Any]])
async def get_events(
    limit: int = Query(50, ge=1, le=500),
    tab: str | None = Query(None, description="Category tab: all, watchlist, intrusions, exits, system"),
    camera_id: str | None = Query(None),
    event_type: str | None = Query(None),
) -> list[dict[str, Any]]:
    raw = list_events()
    # Sort newest first
    raw = sorted(raw, key=lambda e: _parse_timestamp(e.get("created_at")), reverse=True)

    filtered = []
    for ev in raw:
        etype = str(ev.get("event_type", "")).lower()
        if camera_id and ev.get("camera_id") != camera_id:
            continue
        if event_type and etype != event_type.lower():
            continue

        if tab:
            tab_clean = tab.lower().strip()
            if tab_clean in {"watchlist", "watchlist_matches", "watchlist matches"}:
                if not ("watchlist" in etype or "suspect" in etype):
                    continue
            elif tab_clean in {"intrusions", "intrusion"}:
                if "intrusion" not in etype:
                    continue
            elif tab_clean in {"exits", "exit"}:
                if "exit" not in etype:
                    continue
            elif tab_clean in {"system", "sys"}:
                if not ("system" in etype or "low_vis" in etype or "offline" in etype or "reconnect" in etype):
                    continue

        filtered.append(ev)

    return filtered[:limit]


@router.delete("", response_model=dict[str, Any])
async def delete_events() -> dict[str, Any]:
    count = clear_events()
    return {"status": "cleared", "deleted_count": count}


@router.get("/outbox", response_model=list[dict[str, Any]])
async def get_outbox() -> list[dict[str, Any]]:
    return [{"id": o.id, "topic": o.topic, "status": o.status, "dedup_key": o.dedup_key} for o in list_outbox()]
