"""File sandbox and jail validation for local video footage."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException


def _is_dev_or_test_env() -> bool:
    """Return True when running in dev/test (synthetic harness allowed)."""
    try:
        from ibvap.config import Settings

        settings = Settings()
        for attr in ("env", "environment"):
            val = getattr(settings, attr, None)
            if isinstance(val, str) and val:
                return val.lower() in {"dev", "development", "test", "testing"}
        app_env = getattr(getattr(settings, "app", None), "env", None)
        if isinstance(app_env, str) and app_env:
            return app_env.lower() in {"dev", "development", "test", "testing"}
    except Exception:
        pass
    env_val = os.getenv("IBVAP_ENV", "").lower()
    if env_val:
        return env_val in {"dev", "development", "test", "testing"}
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return True


def _synthetic_allowed() -> bool:
    return _is_dev_or_test_env()


def _file_jail_roots() -> list[Path]:
    return list(_cached_jail_roots())


@lru_cache(maxsize=1)
def _cached_jail_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in ("data/uploads", "data/quarantine", "tests/fixtures"):
        with contextlib.suppress(Exception):
            roots.append(Path(candidate).resolve())
    with contextlib.suppress(Exception):
        roots.append(Path(tempfile.gettempdir()).resolve())
    return tuple(roots)


@lru_cache(maxsize=1)
def _cached_writable_jail() -> tuple[Path, ...]:
    roots: list[Path] = []
    for candidate in ("data/uploads", "data/quarantine"):
        with contextlib.suppress(Exception):
            roots.append(Path(candidate).resolve())
    return tuple(roots)


def _clean_file_path(raw_path: str) -> str:
    stripped = raw_path.strip().strip('"').strip("'").strip()
    lower = stripped.lower()
    if lower.startswith("file://localhost/"):
        stripped = stripped[17:]
    elif lower.startswith("file:///"):
        stripped = stripped[8:]
    elif lower.startswith("file://"):
        stripped = stripped[7:]
    elif lower.startswith("file:\\\\\\"):
        stripped = stripped[8:]
    elif lower.startswith("file:\\\\"):
        stripped = stripped[7:]
    elif lower.startswith("file:"):
        stripped = stripped[5:]
    return stripped.strip().strip('"').strip("'").strip()


def _resolve_jailed_file(raw_path: str) -> Path:
    stripped = _clean_file_path(raw_path)
    if ".." in Path(stripped).parts:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_file_path", "message": "Invalid footage path"},
        )
    candidate = Path(stripped)
    try:
        resolved = candidate.resolve()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_file_path", "message": "Invalid footage path"},
        ) from None
    for root in _file_jail_roots():
        try:
            if resolved.is_relative_to(root):
                return resolved
        except Exception:
            continue
    if not candidate.is_absolute():
        for root in _file_jail_roots():
            sub = (root / candidate).resolve()
            try:
                if sub.is_relative_to(root) and sub.exists():
                    return sub
            except Exception:
                continue
    raise HTTPException(
        status_code=400,
        detail={"code": "invalid_file_path", "message": "Invalid footage path"},
    )


def _is_file_endpoint(endpoint: str, protocol: str | None = None) -> bool:
    clean = _clean_file_path(endpoint)
    lower_raw = endpoint.strip().lower()
    if protocol == "file" or lower_raw.startswith(("file://", "file:\\\\", "file:")):
        return True
    if protocol in {"rtsp", "rtsps", "http", "https", "mjpeg", "hls", "whip"}:
        return False
    if "://" in clean and not lower_raw.startswith(("file://", "file:\\\\")):
        return False
    if re.match(r"^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/.*)?$", clean):
        return False
    if re.match(r"^[a-zA-Z]:[/\\]", clean) or clean.startswith(("/", "\\")):
        return True
    return Path(clean).suffix.lower() in {".mp4", ".avi", ".mkv", ".mov", ".webm"}


def _import_external_video_if_needed(endpoint: str) -> str:
    clean = _clean_file_path(endpoint)
    if ".." in Path(clean).parts:
        return endpoint
    try:
        jailed = _resolve_jailed_file(clean)
        return str(jailed)
    except HTTPException:
        return endpoint



def _is_path_inside_jail(path_str: str) -> bool:
    try:
        resolved = Path(path_str).resolve()
    except Exception:
        return False
    for root in _cached_writable_jail():
        try:
            if resolved.is_relative_to(root):
                return True
        except Exception:
            continue
    return False


def _safe_unlink_inside_jail(path_str: str) -> None:
    if not _is_path_inside_jail(path_str):
        return
    with contextlib.suppress(OSError):
        Path(path_str).unlink()
