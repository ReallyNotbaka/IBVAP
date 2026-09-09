"""Credential envelope encryption - separate fields, never in URL.

Phase 1 uses a symmetric key from env `IBVAP_CREDENTIAL_KEY` (32 urlsafe base64 bytes).
Production will use KMS envelope + pgcrypto. For now, Fernet is sufficient and testable.
"""

from __future__ import annotations

import base64
import os
import threading
from typing import Final
from urllib.parse import quote, urlparse, urlunparse

from cryptography.fernet import Fernet, InvalidToken

_ENV_KEY: Final = "IBVAP_CREDENTIAL_KEY"

_FERNET_CACHE: Fernet | None = None
_FERNET_CACHE_KEY: str | None = None
_FERNET_LOCK = threading.Lock()


def _get_fernet() -> Fernet:
    global _FERNET_CACHE, _FERNET_CACHE_KEY
    raw = os.getenv(_ENV_KEY)
    if not raw:
        raise RuntimeError(
            "IBVAP_CREDENTIAL_KEY is required for credential encryption. "
            "Set a valid Fernet key or 32-byte secret before storing camera credentials."
        )

    candidate = raw.strip()
    # Reuse cached instance when env key unchanged (avoids per-request Fernet setup).
    with _FERNET_LOCK:
        if _FERNET_CACHE is not None and candidate == _FERNET_CACHE_KEY:
            return _FERNET_CACHE
    try:
        Fernet(candidate.encode())
        key = candidate.encode()
    except Exception:
        try:
            # treat as 32-byte secret, derive Fernet key via base64
            padded = base64.urlsafe_b64encode(candidate.encode()[:32].ljust(32, b"\0"))
            Fernet(padded)
            key = padded
        except Exception as exc:  # pragma: no cover - defensive validation
            raise ValueError("IBVAP_CREDENTIAL_KEY must be a valid Fernet key or 32-byte secret") from exc
    fernet = Fernet(key)
    with _FERNET_LOCK:
        _FERNET_CACHE = fernet
        _FERNET_CACHE_KEY = candidate
    return fernet


def encrypt_secret(plaintext: str) -> str:
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    f = _get_fernet()
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Failed to decrypt credential") from e


def redact_url(url: str) -> str:
    """Strip credentials and query/fragment secrets from URL for logging / diagnostics."""
    try:
        p = urlparse(url)
        changed = False
        if p.username or p.password:
            netloc = p.hostname or ""
            if p.port:
                netloc = f"{netloc}:{p.port}"
            p = p._replace(netloc=netloc)
            changed = True
        # Tokens live in ?query= and #fragments - never echo those either.
        if p.query or p.fragment:
            p = p._replace(query="", fragment="")
            changed = True
        if changed:
            return urlunparse(p)
    except Exception:
        pass
    return url


def build_authenticated_url(endpoint: str, username: str | None, password: str | None) -> str:
    """Inject userinfo into a validated endpoint for connect-time use.

    The result carries secrets: open streams with it, never persist or log it.
    Returns the endpoint unchanged when there are no credentials or no host.
    """
    if not username and not password:
        return endpoint
    try:
        p = urlparse(endpoint)
        if not p.hostname:
            return endpoint
        userinfo = quote(username or "", safe="")
        if password:
            userinfo += ":" + quote(password, safe="")
        netloc = f"{userinfo}@{p.hostname}"
        if p.port:
            netloc += f":{p.port}"
        return urlunparse(p._replace(netloc=netloc))
    except Exception:
        return endpoint
