"""C2 Webhook Dispatcher and System Settings Engine."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

SETTINGS_PATH = Path("data/settings.json")
logger = logging.getLogger(__name__)


@dataclass
class SystemSettings:
    c2_webhook_url: str | None = None
    c2_webhook_enabled: bool = False
    c2_min_severity: str = "HIGH"  # ALL | HIGH | CRITICAL
    detection_confidence_threshold: float = 0.45
    loiter_cooldown_seconds: float = 10.0
    evidence_retention_days: int = 90


_CURRENT_SETTINGS = SystemSettings()


def load_settings() -> SystemSettings:
    """Load settings from JSON file into memory."""
    global _CURRENT_SETTINGS
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            _CURRENT_SETTINGS = SystemSettings(
                c2_webhook_url=data.get("c2_webhook_url"),
                c2_webhook_enabled=bool(data.get("c2_webhook_enabled", False)),
                c2_min_severity=data.get("c2_min_severity", "HIGH"),
                detection_confidence_threshold=float(data.get("detection_confidence_threshold", 0.45)),
                loiter_cooldown_seconds=float(data.get("loiter_cooldown_seconds", 10.0)),
                evidence_retention_days=int(data.get("evidence_retention_days", 90)),
            )
        except Exception as e:
            logger.warning("Failed to load settings from %s: %s", SETTINGS_PATH, e)
    return _CURRENT_SETTINGS


def save_settings(new_settings: SystemSettings) -> None:
    """Persist settings to data/settings.json."""
    global _CURRENT_SETTINGS
    _CURRENT_SETTINGS = new_settings
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(asdict(new_settings), indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to save settings: %s", e)


def get_settings() -> SystemSettings:
    """Get active runtime settings."""
    return _CURRENT_SETTINGS


async def dispatch_c2_webhook(event: dict[str, Any], base_url: str = "") -> bool:
    """Send alert payload to configured C2 webhook."""
    settings = get_settings()
    if not settings.c2_webhook_enabled or not settings.c2_webhook_url:
        return False

    etype = str(event.get("event_type", "")).lower()
    is_critical = "watchlist" in etype or "suspect" in etype
    is_high = "intrusion" in etype or "line" in etype

    if settings.c2_min_severity == "CRITICAL" and not is_critical:
        return False
    if settings.c2_min_severity == "HIGH" and not (is_critical or is_high):
        return False

    severity = "CRITICAL" if is_critical else ("HIGH" if is_high else "MEDIUM")

    snap_url = event.get("snapshot_url")
    crop_url = event.get("crop_url")
    if snap_url and not snap_url.startswith("http"):
        snap_url = f"{base_url}{snap_url}"
    if crop_url and not crop_url.startswith("http"):
        crop_url = f"{base_url}{crop_url}"

    payload = {
        "event_id": event.get("id"),
        "event_type": event.get("event_type"),
        "severity": severity,
        "camera_id": event.get("camera_id"),
        "zone_id": event.get("zone_id"),
        "timestamp": event.get("created_at"),
        "explanation": event.get("explanation"),
        "confidence": event.get("confidence"),
        "snapshot_url": snap_url,
        "crop_url": crop_url,
    }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(settings.c2_webhook_url, json=payload)
            return resp.status_code < 400
    except Exception as exc:
        logger.warning("C2 webhook dispatch failed: %s", exc)
        return False


async def test_webhook_connection(url: str) -> dict[str, Any]:
    """Send test alert ping to verify external C2 webhook endpoint."""
    test_payload = {
        "event_type": "c2_connection_test",
        "severity": "INFO",
        "message": "IBVAP Command & Control Webhook Operational Test",
        "timestamp": time.time(),
    }
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=test_payload)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "success": resp.status_code < 400,
                "status_code": resp.status_code,
                "elapsed_ms": elapsed_ms,
                "message": (
                    f"Server responded with {resp.status_code} in {elapsed_ms}ms"
                    if resp.status_code < 400
                    else f"HTTP error {resp.status_code}"
                ),
            }
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": elapsed_ms,
            "message": f"Connection failed: {str(e)}",
        }
