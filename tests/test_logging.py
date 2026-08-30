from __future__ import annotations

import json
import logging

from ibvap.logging_setup import JsonFormatter, _redact


def test_redaction() -> None:
    data = {
        "username": "alice",
        "password": "secret123",
        "nested": {"token": "abc", "plate": "MH01AB1234"},
    }
    redacted = _redact(data)
    assert redacted["password"] == "***REDACTED***"
    assert redacted["nested"]["token"] == "***REDACTED***"
    assert redacted["nested"]["plate"] == "***REDACTED***"
    assert redacted["username"] == "alice"


def test_json_formatter_outputs_valid_json(caplog: object) -> None:
    logger = logging.getLogger("test.json")
    logger.setLevel(logging.INFO)
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.json",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    out = formatter.format(record)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "hello"
    assert parsed["service"] == "ibvap"
