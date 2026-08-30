"""WebSocket - Phase 3 slice.

Authenticated via query token (Phase 1 stub allows any).
Envelope per spec 20: schema_version, message_id, message_type, timestamp, sequence, camera_id, site_id, stream_epoch, correlation_id, payload
"""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])

# In-mem per-client queue - bounded as spec
MAX_QUEUE = 64


@router.websocket("/api/v1/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    # auth stub - Phase 2 would check token
    await ws.accept()
    seq = 0
    try:
        for _ in range(3):
            envelope = {
                "schema_version": "v1",
                "message_id": str(uuid.uuid4()),
                "message_type": "heartbeat",
                "timestamp": time.time(),
                "sequence": seq,
                "camera_id": "any",
                "site_id": "any",
                "stream_epoch": 0,
                "correlation_id": str(uuid.uuid4()),
                "payload": {"status": "ok"},
            }
            await ws.send_text(json.dumps(envelope))
            seq += 1
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            await ws.close()
