"""Events timeline - Phase 3 slice."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Query

from ibvap.events.outbox import clear_events, list_events, list_outbox

logger = structlog.get_logger(__name__)

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
                return datetime.fromisoformat(val).timestamp()
            except Exception:
                return 0.0
    return 0.0


# Hoisted tab-category sets to avoid per-event set allocations.
_WATCHLIST_TABS = {"watchlist", "watchlist_matches", "watchlist matches"}
_INTRUSION_TABS = {"intrusions", "intrusion"}
_EXIT_TABS = {"exits", "exit"}
_SYSTEM_TABS = {"system", "sys"}


@router.get("", response_model=list[dict[str, Any]])
async def get_events(
    limit: int = Query(50, ge=1, le=500),
    tab: str | None = Query(None, description="Category tab: all, watchlist, intrusions, exits, system"),
    camera_id: str | None = Query(None),
    event_type: str | None = Query(None),
) -> list[dict[str, Any]]:
    raw = list_events()
    # Hoist filter keys out of the loop (avoids per-event lower()/strip()).
    event_type_lower = event_type.lower() if event_type else None
    tab_clean = tab.lower().strip() if tab else None
    want_watchlist = tab_clean in _WATCHLIST_TABS if tab_clean else False
    want_intrusion = tab_clean in _INTRUSION_TABS if tab_clean else False
    want_exit = tab_clean in _EXIT_TABS if tab_clean else False
    want_system = tab_clean in _SYSTEM_TABS if tab_clean else False

    filtered: list[tuple[float, dict[str, Any]]] = []
    for ev in raw:
        if camera_id and ev.get("camera_id") != camera_id:
            continue
        etype = str(ev.get("event_type", "")).lower()
        if event_type_lower and etype != event_type_lower:
            continue

        if tab_clean:
            if want_watchlist:
                if not ("watchlist" in etype or "suspect" in etype):
                    continue
            elif want_intrusion:
                if "intrusion" not in etype:
                    continue
            elif want_exit:
                if "exit" not in etype:
                    continue
            elif want_system and not (
                "system" in etype or "low_vis" in etype or "offline" in etype or "reconnect" in etype
            ):
                continue

        filtered.append((_parse_timestamp(ev.get("created_at")), ev))

    # Sort only the filtered set newest-first, then apply limit.
    filtered.sort(key=lambda item: item[0], reverse=True)
    if len(filtered) > limit:
        del filtered[limit:]
    return [ev for _, ev in filtered]


@router.delete("", response_model=dict[str, Any])
async def delete_events() -> dict[str, Any]:
    # TODO: require authentication/authorization for mutating routes (would break tests today).
    logger.warning("unauthenticated_delete", route="DELETE /api/v1/events")
    count = clear_events()
    return {"status": "cleared", "deleted_count": count}


@router.get("/outbox", response_model=list[dict[str, Any]])
async def get_outbox() -> list[dict[str, Any]]:
    return [{"id": o.id, "topic": o.topic, "status": o.status, "dedup_key": o.dedup_key} for o in list_outbox()]
