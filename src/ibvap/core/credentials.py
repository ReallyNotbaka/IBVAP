"""Credential envelope encryption - separate fields, never in URL.

Phase 1 uses a symmetric key from env `IBVAP_CREDENTIAL_KEY` (32 urlsafe base64 bytes).
Production will use KMS envelope + pgcrypto. For now, Fernet is sufficient and testable.
"""

from __future__ import annotations

import base64
import os
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

_ENV_KEY: Final = "IBVAP_CREDENTIAL_KEY"


def _get_fernet() -> Fernet:
    raw = os.getenv(_ENV_KEY)
    if not raw:
        raise RuntimeError(
            "IBVAP_CREDENTIAL_KEY is required for credential encryption. "
            "Set a valid Fernet key or 32-byte secret before storing camera credentials."
        )

    candidate = raw.strip()
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
    return Fernet(key)


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
    """Strip credentials from URL for logging / diagnostics."""
    from urllib.parse import urlparse, urlunparse

    try:
        p = urlparse(url)
        if p.username or p.password:
            netloc = p.hostname or ""
            if p.port:
                netloc = f"{netloc}:{p.port}"
            p = p._replace(netloc=netloc)
            return urlunparse(p)
    except Exception:
        pass
    return url
