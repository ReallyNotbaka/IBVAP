"""WebSocket - Phase 3 development preview stub (non-production).

IMPORTANT:
This endpoint is a development/preview stub and NOT a production event transport.
The production system uses REST polling on /api/v1/events and /api/v1/cameras,
backed by the PostgreSQL transactional outbox (ADR-0005).
By default, this endpoint is disabled (enable_ws=False) to prevent creating
a false production capability.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])

# In-mem per-client queue - bounded as spec
MAX_QUEUE = 64

_HEARTBEAT_TEMPLATE = {
    "schema_version": "v1",
    "message_type": "heartbeat",
    "camera_id": "any",
    "site_id": "any",
    "stream_epoch": 0,
    "payload": {"status": "ok"},
}


@router.websocket("/api/v1/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    from ibvap.config import Settings

    settings = getattr(ws.app.state, "settings", None) or Settings()
    enable_ws = getattr(getattr(settings, "app", None), "enable_ws", False)
    if not enable_ws:
        # Prevent creating false production capability: reject immediately
        await ws.close(
            code=1008,
            reason="WebSocket event transport is disabled. Use REST polling on /api/v1/events.",
        )
        return

    await ws.accept()
    # Explicit development notice envelope
    notice = {
        "schema_version": "v1",
        "message_type": "system.notice",
        "camera_id": "any",
        "site_id": "any",
        "stream_epoch": 0,
        "payload": {
            "status": "development_only",
            "detail": "WebSocket is a non-production Phase 3 stub. Production clients must use REST polling on /api/v1/events.",
        },
        "message_id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "sequence": 0,
        "correlation_id": str(uuid.uuid4()),
    }
    await ws.send_text(json.dumps(notice))

    seq = 1
    try:
        while True:
            try:
                # Wait up to 5s for client message or disconnect
                await asyncio.wait_for(ws.receive_text(), timeout=5.0)
            except TimeoutError:
                # Heartbeat interval elapsed
                envelope = {
                    **_HEARTBEAT_TEMPLATE,
                    "message_id": str(uuid.uuid4()),
                    "timestamp": time.time(),
                    "sequence": seq,
                    "correlation_id": str(uuid.uuid4()),
                }
                await ws.send_text(json.dumps(envelope))
                seq += 1
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
