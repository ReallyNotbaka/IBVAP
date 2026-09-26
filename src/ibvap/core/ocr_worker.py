"""Vehicle ANPR track matching and plate detection selection helpers."""

from __future__ import annotations

from typing import Any

ANPR_DISPLAY_CONFIDENCE = 0.55


def _boxes_intersect(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    """Return True if normalized bounding boxes a and b intersect."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _match_vehicle_track(
    det_bbox: tuple[float, float, float, float],
    tracks: list[Any],
) -> int:
    """Max-IoU vehicle track match. Returns track_id, or 0 when nothing overlaps.

    Raw overlap area cannot tell nesting (a corner-touching bus ties the true
    owner and order decides); IoU normalizes by union so the owning track wins.
    """
    best_id = 0
    best_iou = 0.0
    x1, y1, x2, y2 = det_bbox
    det_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    for track in tracks:
        tx1, ty1, tx2, ty2 = track.bbox_norm
        ox = min(x2, tx2) - max(x1, tx1)
        oy = min(y2, ty2) - max(y1, ty1)
        if ox <= 0.0 or oy <= 0.0:
            continue
        inter = ox * oy
        union = det_area + max(0.0, tx2 - tx1) * max(0.0, ty2 - ty1) - inter
        iou = inter / union if union > 0.0 else 0.0
        if iou > best_iou:
            best_iou = iou
            best_id = track.track_id
    return best_id


def _select_plate_detections(
    fresh: list[dict[str, Any]],
    cached: list[dict[str, Any]],
    cached_at_mono: float,
    now_mono: float,
    vehicle_boxes: list[tuple[float, float, float, float]],
    max_age_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Publish cached OCR boxes only while fresh AND a vehicle is still there.

    OCR completes hundreds of ms after its frame; blindly republishing the
    last batch ghosts departed vehicles (and a low-conf batch wipes a live
    plate). Reuse requires age <= max_age_s plus overlap between a cached
    box and a current-frame vehicle box.
    """
    if cached and (now_mono - cached_at_mono) <= max_age_s:
        cached_boxes = [d["bbox_norm"] for d in cached if "bbox_norm" in d]
        if any(_boxes_intersect(cb, vb) for cb in cached_boxes for vb in vehicle_boxes):
            return cached
    return fresh
