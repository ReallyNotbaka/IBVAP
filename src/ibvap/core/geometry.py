"""Image geometry - letterbox, normalize, polygon validation. Spec 11."""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LetterboxParams:
    scale: float
    pad_x: float
    pad_y: float
    src_w: int
    src_h: int
    model_size: int


@functools.lru_cache(maxsize=32)
def letterbox_params(src_w: int, src_h: int, model_size: int = 640) -> LetterboxParams:
    # Cached: source resolution is invariant per camera stream, so repeated
    # per-frame calls with the same (w, h, size) hit the cache (no re-alloc).
    scale = min(model_size / src_w, model_size / src_h) if src_w and src_h else 1.0
    new_w = src_w * scale
    new_h = src_h * scale
    pad_x = (model_size - new_w) / 2.0
    pad_y = (model_size - new_h) / 2.0
    return LetterboxParams(scale=scale, pad_x=pad_x, pad_y=pad_y, src_w=src_w, src_h=src_h, model_size=model_size)


def to_model_coords(x_norm: float, y_norm: float, p: LetterboxParams) -> tuple[float, float]:
    """Normalized [0,1] source -> model input coords."""
    x_src = x_norm * p.src_w
    y_src = y_norm * p.src_h
    return (x_src * p.scale + p.pad_x, y_src * p.scale + p.pad_y)


def to_source_norm(x_model: float, y_model: float, p: LetterboxParams) -> tuple[float, float]:
    """Model coords -> normalized source."""
    x_src = (x_model - p.pad_x) / p.scale
    y_src = (y_model - p.pad_y) / p.scale
    return (x_src / p.src_w if p.src_w else 0.0, y_src / p.src_h if p.src_h else 0.0)


def on_seg(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])


def _orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def intersect(p1: tuple[float, float], p2: tuple[float, float], q1: tuple[float, float], q2: tuple[float, float]) -> bool:
    # Module-level _orient avoids allocating a nested closure on every call
    # (hot: line-tripwire checks run per track per frame, plus trajectory scan).
    o1 = _orient(p1, p2, q1)
    o2 = _orient(p1, p2, q2)
    o3 = _orient(q1, q2, p1)
    o4 = _orient(q1, q2, p2)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if o1 == 0 and on_seg(p1, q1, p2):
        return True
    if o2 == 0 and on_seg(p1, q2, p2):
        return True
    if o3 == 0 and on_seg(q1, p1, q2):
        return True
    return bool(o4 == 0 and on_seg(q1, p2, q2))


def point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from point (px, py) to segment AB."""
    dx = bx - ax
    dy = by - ay
    l2 = dx * dx + dy * dy
    if l2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def segment_intersects_bbox(ax: float, ay: float, bx: float, by: float, bbox: tuple[float, float, float, float]) -> bool:
    """True if segment AB touches or crosses the normalized bounding box (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = bbox
    # Check if either endpoint is inside bbox
    if x1 <= ax <= x2 and y1 <= ay <= y2:
        return True
    if x1 <= bx <= x2 and y1 <= by <= y2:
        return True
    p1 = (ax, ay)
    p2 = (bx, by)
    # Unrolled edge checks: avoids allocating the 4-tuple box_edges list
    # on every call (hot: segment-vs-bbox tested per frame).
    return (
        intersect(p1, p2, (x1, y1), (x2, y1))
        or intersect(p1, p2, (x2, y1), (x2, y2))
        or intersect(p1, p2, (x2, y2), (x1, y2))
        or intersect(p1, p2, (x1, y2), (x1, y1))
    )


def validate_line(points: list[list[float]]) -> str | None:
    """Validate 2-point line fence/tripwire."""
    if len(points) != 2:
        return "Line fence requires exactly 2 points"
    for x, y in points:
        if not (math.isfinite(x) and math.isfinite(y)):
            return "Non-finite coordinate"
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return "Coordinate out of [0,1]"
    x1, y1 = points[0]
    x2, y2 = points[1]
    if math.hypot(x2 - x1, y2 - y1) < 0.005:
        return "Line too short"
    return None


def validate_polygon(points: list[list[float]]) -> str | None:
    """Validate polygon per spec 11. Returns error string or None if valid.

    Checks: finite, within [0,1], >=3 unique, non-zero area, no self-intersection (simple),
    min edge, max vertex 32.
    """
    if len(points) < 3:
        return "Polygon needs >=3 vertices"
    if len(points) > 32:
        return "Too many vertices (max 32)"
    # unique
    uniq = {tuple(p) for p in points}
    if len(uniq) < 3:
        return "Need >=3 unique vertices"
    for x, y in points:
        if not (math.isfinite(x) and math.isfinite(y)):
            return "Non-finite coordinate"
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return "Coordinate out of [0,1]"
    # area via shoelace
    area = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    if abs(area) < 1e-6:
        return "Zero area"
    # edge length minimum
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        if math.hypot(x2 - x1, y2 - y1) < 0.005:
            return "Edge too short"

    n = len(points)
    pts_t: list[tuple[float, float]] = [(float(p[0]), float(p[1])) for p in points]
    for i in range(n):
        for j in range(i + 1, n):
            # skip adjacent and closing edge share a vertex
            if abs(i - j) <= 1 or (i == 0 and j == n - 1) or (j == 0 and i == n - 1):
                continue
            if intersect(pts_t[i], pts_t[(i + 1) % n], pts_t[j], pts_t[(j + 1) % n]):
                return "Self-intersection"
    return None


def validate_fence(points: list[list[float]], fence_type: str = "auto") -> str | None:
    """Validate fence points for line or polygon configuration."""
    if fence_type == "line":
        return validate_line(points)
    if fence_type == "polygon":
        return validate_polygon(points)
    if len(points) == 2:
        return validate_line(points)
    return validate_polygon(points)


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray casting - uses normalized coords. Returns True if inside."""
    inside = False
    n = len(polygon)
    # Localise list access in the hot per-track-per-frame loop.
    poly = polygon
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1):
            inside = not inside
    return inside
