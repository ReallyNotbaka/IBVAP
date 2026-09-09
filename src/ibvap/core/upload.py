"""Upload quarantine - spec 21.2."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

ALLOWED_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
MAX_DURATION_SECS = 2 * 3600
QUARANTINE_DIR = Path("data/quarantine")
PROMOTED_DIR = Path("data/uploads")


def ensure_dirs() -> None:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    PROMOTED_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_dir(path: Path) -> None:
    # Fast path: skip mkdir syscall when dir already exists.
    if path.is_dir():
        return
    path.mkdir(parents=True, exist_ok=True)


def validate_filename(name: str) -> None:
    p = Path(name)
    if p.suffix.lower() not in ALLOWED_EXTS:
        raise ValueError(f"Unsupported extension {p.suffix}")
    # prevent path traversal
    if ".." in Path(name).parts or name.startswith("/") or ":" in name:
        raise ValueError("Invalid filename")


def quarantine_path(upload_id: str, original_name: str) -> Path:
    _ensure_dir(QUARANTINE_DIR)
    ext = Path(original_name).suffix.lower()
    # generated object name - no client path
    safe = f"{upload_id}{ext}"
    return QUARANTINE_DIR / safe


def promoted_path(upload_id: str, original_name: str) -> Path:
    _ensure_dir(PROMOTED_DIR)
    ext = Path(original_name).suffix.lower()
    return PROMOTED_DIR / f"{upload_id}{ext}"


def streaming_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def new_upload_id() -> str:
    return uuid.uuid4().hex
