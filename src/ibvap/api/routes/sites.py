"""Sites CRUD - minimal Phase 2."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/sites", tags=["sites"])

_SITES: dict[str, dict[str, Any]] = {}


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    organization_id: str
    timezone: str = "UTC"


@router.post("", response_model=dict[str, Any])
async def create_site(req: SiteCreate) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    data = {"id": sid, "name": req.name, "organization_id": req.organization_id, "timezone": req.timezone}
    _SITES[sid] = data
    return data


@router.get("", response_model=list[dict[str, Any]])
async def list_sites() -> list[dict[str, Any]]:
    return list(_SITES.values())
