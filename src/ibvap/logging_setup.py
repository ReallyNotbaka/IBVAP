"""Structured JSON logging - no secrets / PII."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Sensitive keys that must never appear in logs
_REDACT_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "credential",
    "plate",
    "embedding",
}


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k.lower() in _REDACT_KEYS or "password" in k.lower() or "secret" in k.lower():
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "ibvap",
            "version": "0.1.0",
        }
        # attach structured extras if present
        extra = {k: v for k, v in record.__dict__.items() if k not in logging.LogRecord.__dict__}
        if extra:
            payload["extra"] = _redact(extra)
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_level: str = "INFO", log_dir: str = "data/logs") -> None:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)
    # also file handler
    try:
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(str(path / "ibvap.log"), maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    except Exception:
        pass
