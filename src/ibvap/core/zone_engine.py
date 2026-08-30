"""Zone engine - one polygon intrusion rule for Phase 3 slice.

Spec 13: uses bottom-center footpoint for person/vehicle zone logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from ibvap.core.geometry import point_in_polygon


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: list[list[float]]  # normalized [0,1]
    enabled: bool = True


def is_intrusion(track_foot: tuple[float, float], zone: Zone) -> bool:
    if not zone.enabled:
        return False
    return point_in_polygon(track_foot[0], track_foot[1], zone.polygon)


# Default zone for Phase 3 slice - central restricted rectangle
DEFAULT_ZONE = Zone(
    id="zone-restricted-1",
    name="Restricted Zone",
    polygon=[[0.35, 0.35], [0.65, 0.35], [0.65, 0.65], [0.35, 0.65]],
    enabled=True,
)
