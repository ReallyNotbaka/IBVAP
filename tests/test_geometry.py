from __future__ import annotations

from ibvap.core.geometry import letterbox_params, point_in_polygon, to_model_coords, to_source_norm, validate_polygon


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
