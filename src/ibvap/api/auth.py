"""Task 1 P0: API-token auth guard for mutating routes.

Fail-closed stub (NOT JWT/OIDC by design): every DELETE/POST/PUT route requires
the ``IBVAP_API_TOKEN`` value via ``X-API-Token`` (or ``Authorization: Bearer
<token>``); missing/mismatched/unconfigured token yields 401. There is no
anonymous mode — local dev sets a token in ``.env`` (see ``.env.example``).

Contract for Task 5 / frontend: send ``X-API-Token: <token>`` on all mutating
calls; ``require_api_token`` stays intact as the shared dependency.
"""

from __future__ import annotations

import hmac
import os
from typing import Annotated

import structlog
from fastapi import Header, HTTPException, Request

logger = structlog.get_logger(__name__)

TOKEN_ENV_VAR = "IBVAP_API_TOKEN"
TOKEN_HEADER = "X-API-Token"


def _expected_token() -> str:
    return os.getenv(TOKEN_ENV_VAR, "")


async def require_api_token(
    request: Request,
    x_api_token: Annotated[str | None, Header(alias=TOKEN_HEADER)] = None,
) -> bool:
    """FastAPI dependency: enforce API token on mutating routes (Task 1 P0).

    Fail-closed (fix-round 1): no anonymous mode. A missing/unconfigured
    expected token is itself a 401 — never allow.
    """
    expected = _expected_token()
    provided = (x_api_token or "").strip()
    if not provided:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        logger.warning("auth_rejected", route=request.url.path)
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
    return True


# Alias per brief Step 3 naming (``Depends(get_current_user)``); same guard.
get_current_user = require_api_token
