from __future__ import annotations

from ibvap.core.geometry import (
    letterbox_params,
    point_in_polygon,
    point_to_segment_distance,
    segment_intersects_bbox,
    to_model_coords,
    to_source_norm,
    validate_fence,
    validate_line,
    validate_polygon,
)
from ibvap.core.zone_engine import Zone, is_intrusion


def test_letterbox_roundtrip() -> None:
    p = letterbox_params(1920, 1080, 640)
    # top-left normalized (0,0) -> model
    mx, my = to_model_coords(0.0, 0.0, p)
    # back to source
    x, y = to_source_norm(mx, my, p)
    assert abs(x) < 1e-6
    assert abs(y) < 1e-6
    # center
    mx, my = to_model_coords(0.5, 0.5, p)
    x, y = to_source_norm(mx, my, p)
    assert abs(x - 0.5) < 1e-6
    assert abs(y - 0.5) < 1e-6


def test_validate_polygon_ok() -> None:
    ok = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    assert validate_polygon(ok) is None


def test_validate_polygon_self_intersection() -> None:
    # bowtie - should be invalid (either zero area or self-intersection, both are rejected)
    bow = [[0.2, 0.2], [0.8, 0.8], [0.8, 0.2], [0.2, 0.8]]
    assert validate_polygon(bow) is not None


def test_validate_polygon_too_few() -> None:
    assert validate_polygon([[0.1, 0.1], [0.2, 0.2]]) is not None


def test_point_in_polygon() -> None:
    poly = [[0.35, 0.35], [0.65, 0.35], [0.65, 0.65], [0.35, 0.65]]
    assert point_in_polygon(0.5, 0.5, poly) is True
    assert point_in_polygon(0.1, 0.1, poly) is False


def test_hypothesis_polygon_property():
    # simple property: any valid polygon should pass validate, and its bbox center should be inside or not far
    # we use deterministic set instead of hypothesis for speed in this slice
    polys = [
        [[0.2, 0.2], [0.5, 0.2], [0.5, 0.5], [0.2, 0.5]],
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
    ]
    for poly in polys:
        assert validate_polygon(poly) is None


def test_validate_line_ok() -> None:
    line = [[0.1, 0.2], [0.8, 0.9]]
    assert validate_line(line) is None
    assert validate_fence(line, fence_type="line") is None
    assert validate_fence(line, fence_type="auto") is None


def test_validate_line_invalid() -> None:
    # Too few / too many points
    assert validate_line([[0.1, 0.2]]) is not None
    assert validate_line([[0.1, 0.2], [0.5, 0.5], [0.9, 0.9]]) is not None
    # Too short
    assert validate_line([[0.1, 0.1], [0.1001, 0.1001]]) is not None
    # Out of bounds
    assert validate_line([[-0.1, 0.2], [0.5, 0.5]]) is not None


def test_point_to_segment_distance() -> None:
    # Distance from (0.5, 0.6) to horizontal segment (0.0, 0.5) -> (1.0, 0.5) is 0.1
    d = point_to_segment_distance(0.5, 0.6, 0.0, 0.5, 1.0, 0.5)
    assert abs(d - 0.1) < 1e-6
    # Off end of segment
    d2 = point_to_segment_distance(1.5, 0.5, 0.0, 0.5, 1.0, 0.5)
    assert abs(d2 - 0.5) < 1e-6


def test_segment_intersects_bbox() -> None:
    bbox = (0.2, 0.2, 0.4, 0.4)
    # Crossing segment
    assert segment_intersects_bbox(0.1, 0.3, 0.5, 0.3, bbox) is True
    # Segment inside
    assert segment_intersects_bbox(0.25, 0.25, 0.35, 0.35, bbox) is True
    # Segment outside
    assert segment_intersects_bbox(0.6, 0.6, 0.8, 0.8, bbox) is False


def test_line_fence_is_intrusion() -> None:
    zone = Zone(
        id="test-line-zone",
        name="Tripwire",
        polygon=[[0.1, 0.5], [0.9, 0.5]],
        fence_type="line",
    )
    # Footpoint close to line
    assert is_intrusion((0.5, 0.51), zone) is True
    # Footpoint far from line
    assert is_intrusion((0.5, 0.8), zone) is False

    # Previous footpoint crossing line
    assert is_intrusion((0.5, 0.7), zone, prev_foot=(0.5, 0.3)) is True

    # Disabled zone never flags intrusion
    disabled_zone = Zone(
        id="test-disabled-zone",
        name="Tripwire Disabled",
        polygon=[[0.1, 0.5], [0.9, 0.5]],
        fence_type="line",
        enabled=False,
    )
    assert is_intrusion((0.5, 0.5), disabled_zone) is False

    # Track object with prev_footpoint property automatically checked
    from ibvap.core.tracker import Track

    trk = Track(
        track_id=42,
        class_name="person",
        class_id=0,
        bbox_norm=(0.4, 0.6, 0.6, 0.8),
        confidence=0.9,
    )
    # Target jumped across line from y2 = 0.3 to y2 = 0.8
    trk.prev_bbox_norm = (0.4, 0.1, 0.6, 0.3)
    assert trk.prev_footpoint == (0.5, 0.3)
    assert trk.footpoint == (0.5, 0.8)
    assert is_intrusion(trk.footpoint, zone, track=trk) is True
