"""Alert workflow - Phase 5, spec 17.

States: open -> acknowledged -> assigned -> resolved/dismissed with audit.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

AlertState = Literal["open", "acknowledged", "assigned", "resolved", "dismissed"]
AlertSeverity = Literal["low", "medium", "high", "critical"]


@dataclass
class Alert:
    id: str
    event_id: str
    camera_id: str
    severity: AlertSeverity
    state: AlertState = "open"
    assignee: str | None = None
    audit: list[dict] = field(default_factory=list)

    def _log(self, action: str, actor: str, note: str = "") -> None:
        self.audit.append({"ts": time.time(), "action": action, "actor": actor, "note": note, "state": self.state})

    def acknowledge(self, actor: str) -> None:
        if self.state != "open":
            raise ValueError(f"Cannot acknowledge from {self.state}")
        self.state = "acknowledged"
        self._log("acknowledge", actor)

    def assign(self, assignee: str, actor: str) -> None:
        if self.state not in {"open", "acknowledged"}:
            raise ValueError(f"Cannot assign from {self.state}")
        self.assignee = assignee
        self.state = "assigned"
        self._log("assign", actor, note=f"to {assignee}")

    def resolve(self, actor: str) -> None:
        if self.state not in {"acknowledged", "assigned"}:
            raise ValueError(f"Cannot resolve from {self.state}")
        self.state = "resolved"
        self._log("resolve", actor)

    def dismiss(self, actor: str, reason: str) -> None:
        if not reason:
            raise ValueError("Dismiss reason required")
        self.state = "dismissed"
        self._log("dismiss", actor, note=reason)


_ALERTS: dict[str, Alert] = {}


def create_alert(event_id: str, camera_id: str, severity: AlertSeverity = "high") -> Alert:
    aid = str(uuid.uuid4())
    a = Alert(id=aid, event_id=event_id, camera_id=camera_id, severity=severity)
    a._log("create", "system")
    _ALERTS[aid] = a
    return a


def get_alert(alert_id: str) -> Alert | None:
    return _ALERTS.get(alert_id)
