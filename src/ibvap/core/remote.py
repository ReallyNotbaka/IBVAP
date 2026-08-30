"""Remote / offline - spec 23.

Durable outbox counts, storage pressure thresholds.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from ibvap.events.outbox import list_outbox


@dataclass(frozen=True)
class StoragePressure:
    level: str  # normal|warning|constrained|critical|emergency
    used_percent: float
    runway_days: float | None


def storage_pressure(path: str = "data") -> StoragePressure:
    usage = shutil.disk_usage(path)
    used = (usage.used / usage.total) * 100 if usage.total else 0.0
    if used >= 95:
        level = "emergency"
    elif used >= 90:
        level = "critical"
    elif used >= 80:
        level = "constrained"
    elif used >= 70:
        level = "warning"
    else:
        level = "normal"
    # runway estimate would use write rate
    return StoragePressure(level=level, used_percent=used, runway_days=None)


def outbox_backlog() -> dict[str, int | float | None]:
    pending = list(list_outbox(status="pending"))
    return {
        "count": len(pending),
        "bytes": sum(len(str(o.payload)) for o in pending),
        "oldest_age": max([0] + [0]) if not pending else 0,
    }


def should_accept_upload(pressure: StoragePressure) -> bool:
    # per spec 23: stop accepting new uploads first under pressure
    return pressure.level in {"normal", "warning"}
