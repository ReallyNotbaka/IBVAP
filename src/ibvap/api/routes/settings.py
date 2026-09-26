"""System settings and C2 dispatch configuration API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ibvap.core.dispatcher import (
    SystemSettings,
    get_settings,
    save_settings,
    test_webhook_connection,
)

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class SettingsUpdate(BaseModel):
    c2_webhook_url: str | None = None
    c2_webhook_enabled: bool = False
    c2_min_severity: str = Field(default="HIGH", pattern="^(ALL|HIGH|CRITICAL)$")
    detection_confidence_threshold: float = Field(default=0.45, ge=0.1, le=0.95)
    loiter_cooldown_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    evidence_retention_days: int = Field(default=90, ge=1, le=365)


class WebhookTestRequest(BaseModel):
    url: str


@router.get("/settings", response_model=dict[str, Any])
async def get_system_settings() -> dict[str, Any]:
    """Retrieve runtime settings and C2 dispatch configuration."""
    s = get_settings()
    return {
        "c2_webhook_url": s.c2_webhook_url,
        "c2_webhook_enabled": s.c2_webhook_enabled,
        "c2_min_severity": s.c2_min_severity,
        "detection_confidence_threshold": s.detection_confidence_threshold,
        "loiter_cooldown_seconds": s.loiter_cooldown_seconds,
        "evidence_retention_days": s.evidence_retention_days,
    }


@router.post("/settings", response_model=dict[str, Any])
async def update_system_settings(body: SettingsUpdate) -> dict[str, Any]:
    """Update runtime settings and C2 dispatch configuration."""
    new_s = SystemSettings(
        c2_webhook_url=body.c2_webhook_url,
        c2_webhook_enabled=body.c2_webhook_enabled,
        c2_min_severity=body.c2_min_severity,
        detection_confidence_threshold=body.detection_confidence_threshold,
        loiter_cooldown_seconds=body.loiter_cooldown_seconds,
        evidence_retention_days=body.evidence_retention_days,
    )
    save_settings(new_s)
    return {"status": "saved", "settings": body.model_dump()}


@router.post("/webhook/test", response_model=dict[str, Any])
async def test_c2_webhook(body: WebhookTestRequest) -> dict[str, Any]:
    """Send test alert ping to verify external C2 webhook."""
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Webhook URL must begin with http:// or https://")
    return await test_webhook_connection(body.url)
