"""System settings and C2 dispatch configuration API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter

from ibvap.api.auth import require_api_token
from ibvap.core.dispatcher import (
    SystemSettings,
    get_settings,
    save_settings,
    test_webhook_connection,
    validate_webhook_url,
)
from ibvap.core.ssrf import SSRFError

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


_WEBHOOK_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)


def _check_webhook_url_or_400(url: str | None) -> None:
    """Task 1 P0 fix-round 1: HttpUrl + SSRF policy check. Raises HTTPException(400).

    Strict: any SSRFError — including transient DNS failure — is a 400 at save
    time. Unresolvable hosts cannot be proven safe, so they are not persisted.
    """
    if not url:
        return
    try:
        _WEBHOOK_URL_ADAPTER.validate_python(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook URL must be a valid http:// or https:// URL") from None
    try:
        validate_webhook_url(url)
    except SSRFError as e:
        raise HTTPException(status_code=400, detail=f"Webhook URL blocked ({e.code}): {e.safe_message}") from e


@router.post("/settings", response_model=dict[str, Any])
async def update_system_settings(body: SettingsUpdate, _auth: bool = Depends(require_api_token)) -> dict[str, Any]:
    """Update runtime settings and C2 dispatch configuration."""
    # Task 1 P0: validate c2_webhook_url on save, not just on test.
    _check_webhook_url_or_400(body.c2_webhook_url)
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
async def test_c2_webhook(body: WebhookTestRequest, _auth: bool = Depends(require_api_token)) -> dict[str, Any]:
    """Send test alert ping to verify external C2 webhook."""
    try:
        _WEBHOOK_URL_ADAPTER.validate_python(body.url)
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook URL must be a valid http:// or https:// URL") from None
    try:
        return await test_webhook_connection(body.url)
    except SSRFError as e:
        if e.code in ("dns_failed", "unreachable"):
            return {
                "success": False,
                "status_code": 0,
                "elapsed_ms": 0.0,
                "message": f"Connection failed: {e.safe_message}",
            }
        raise HTTPException(status_code=400, detail=f"Webhook URL blocked ({e.code}): {e.safe_message}") from e
