"""Fence check. Polygon = inside test, 2-point line = tripwire distance check.

Uses the track footpoint (bottom-center), not the box center - otherwise tall
boxes trigger early. Line trips if within ~0.045 normalized units or the
trajectory crossed it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ibvap.core.geometry import (
    intersect,
    point_in_polygon,
    point_to_segment_distance,
)


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    polygon: list[list[float]]  # normalized [0,1]
    enabled: bool = True
    fence_type: str = "polygon"  # "polygon" or "line"

    @property
    def is_line(self) -> bool:
        return self.fence_type == "line" or len(self.polygon) == 2


def is_intrusion(
    track_foot: tuple[float, float],
    zone: Zone,
    prev_foot: tuple[float, float] | None = None,
    track: Any | None = None,
) -> bool:
    if not zone.enabled:
        return False
    if zone.is_line:
        poly = zone.polygon
        if len(poly) < 2:
            return False
        p1 = (float(poly[0][0]), float(poly[0][1]))
        p2 = (float(poly[1][0]), float(poly[1][1]))
        fx, fy = track_foot[0], track_foot[1]
        # 1. Footpoint close to line segment
        dist = point_to_segment_distance(fx, fy, p1[0], p1[1], p2[0], p2[1])
        if dist <= 0.045:
            return True
        # 2. Movement from previous footpoint intersects line segment
        effective_prev_foot = prev_foot if prev_foot is not None else getattr(track, "prev_footpoint", None) if track is not None else None
        if effective_prev_foot is not None and intersect(effective_prev_foot, track_foot, p1, p2):
            return True
        # 3. Trajectory movement intersects line segment
        if track is not None:
            traj = getattr(track, "trajectory", [])
            if len(traj) >= 2:
                start_k = max(0, len(traj) - 6)
                for k in range(start_k, len(traj) - 1):
                    if intersect(traj[k], traj[k + 1], p1, p2):
                        return True
                if intersect(traj[-1], track_foot, p1, p2):
                    return True
        return False
    return point_in_polygon(track_foot[0], track_foot[1], zone.polygon)


# Default zone for the live demo - lower perimeter area of the camera view.
DEFAULT_ZONE = Zone(
    id="zone-restricted-1",
    name="Restricted Zone",
    polygon=[[0.05, 0.20], [0.95, 0.20], [0.95, 1.0], [0.05, 1.0]],
    enabled=True,
    fence_type="polygon",
)
