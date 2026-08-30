"""Simple centroid tracker - ByteTrack stub for Phase 3 slice.

Spec 12: ByteTrack as initial tracker; Phase 3 uses this minimal centroid tracker
to prove ID persistence within camera+epoch without heavy supervision deps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Track:
    track_id: int
    class_name: str
    class_id: int
    bbox_norm: tuple[float, float, float, float]  # x1,y1,x2,y2 normalized
    confidence: float
    age: int = 0  # frames since last seen
    hits: int = 1
    first_seen: float = 0.0
    last_seen: float = 0.0
    trajectory: list[tuple[float, float]] = field(default_factory=list)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_norm
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def footpoint(self) -> tuple[float, float]:
        # bottom-center per spec 11 for person/vehicle zone logic
        x1, y1, x2, y2 = self.bbox_norm
        return ((x1 + x2) / 2.0, y2)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / max(1e-9, area_a + area_b - inter)


class CentroidTracker:
    """Camera-scoped tracker - IDs reset on stream_epoch bump."""

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 15) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.tracks: dict[int, Track] = {}
        self._next_id = 1
        self.stream_epoch = 0

    def reset_epoch(self, new_epoch: int) -> None:
        self.stream_epoch = new_epoch
        self.tracks.clear()
        self._next_id = 1

    def update(self, detections: list[dict[str, Any]], timestamp: float) -> tuple[list[Track], list[Track], list[Track]]:
        """Update with detections. Returns (all_tracks, new_entries, terminated).

        detections: list of {bbox_norm, class_name, class_id, confidence}
        """
        # age existing
        for t in self.tracks.values():
            t.age += 1

        matched: set[int] = set()
        new_entries: list[Track] = []

        for det in detections:
            bbox = det["bbox_norm"]
            # find best iou match among unmatched tracks of same class
            best_id: int | None = None
            best_iou = self.iou_threshold
            for tid, trk in self.tracks.items():
                if tid in matched:
                    continue
                if trk.class_name != det["class_name"]:
                    continue
                iou = _iou(trk.bbox_norm, bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_id = tid
            if best_id is not None:
                trk = self.tracks[best_id]
                trk.bbox_norm = bbox
                trk.confidence = float(det["confidence"])
                trk.age = 0
                trk.hits += 1
                trk.last_seen = timestamp
                trk.trajectory.append(trk.center)
                if len(trk.trajectory) > 64:
                    trk.trajectory.pop(0)
                matched.add(best_id)
            else:
                # new track
                tid = self._next_id
                self._next_id += 1
                trk = Track(
                    track_id=tid,
                    class_name=det["class_name"],
                    class_id=int(det["class_id"]),
                    bbox_norm=bbox,
                    confidence=float(det["confidence"]),
                    age=0,
                    hits=1,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    trajectory=[((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)],
                )
                self.tracks[tid] = trk
                new_entries.append(trk)
                matched.add(tid)

        # purge aged
        terminated: list[Track] = []
        for tid in list(self.tracks.keys()):
            if self.tracks[tid].age > self.max_age:
                terminated.append(self.tracks.pop(tid))

        return list(self.tracks.values()), new_entries, terminated
