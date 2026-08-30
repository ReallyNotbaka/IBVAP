"""Image geometry - letterbox, normalize, polygon validation. Spec 11."""

from __future__ import annotations

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


def letterbox_params(src_w: int, src_h: int, model_size: int = 640) -> LetterboxParams:
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

    # self-intersection naive O(n^2) segment check
    def on_seg(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])

    def intersect(p1: tuple[float, float], p2: tuple[float, float], q1: tuple[float, float], q2: tuple[float, float]) -> bool:
        def orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        o1 = orient(p1, p2, q1)
        o2 = orient(p1, p2, q2)
        o3 = orient(q1, q2, p1)
        o4 = orient(q1, q2, p2)
        if o1 * o2 < 0 and o3 * o4 < 0:
            return True
        if o1 == 0 and on_seg(p1, q1, p2):
            return True
        if o2 == 0 and on_seg(p1, q2, p2):
            return True
        if o3 == 0 and on_seg(q1, p1, q2):
            return True
        return bool(o4 == 0 and on_seg(q1, p2, q2))

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


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray casting - uses normalized coords. Returns True if inside."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-9) + x1):
            inside = not inside
    return inside
