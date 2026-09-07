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
    identity: dict[str, Any] | None = None
    identity_locked: bool = False
    match_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_norm
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def footpoint(self) -> tuple[float, float]:
        # bottom-center per spec 11 for person/vehicle zone logic
        x1, y1, x2, y2 = self.bbox_norm
        return ((x1 + x2) / 2.0, y2)

    def record_biometric_match(
        self,
        entry_id: str,
        name: str,
        score: float,
        tier: str,
    ) -> bool:
        """Record face recognition match and apply 2-of-3 temporal confirmation latch.
        
        Returns True if identity is confirmed and locked.
        """
        match_info = {
            "entry_id": entry_id,
            "name": name,
            "score": score,
            "tier": tier,
        }
        self.match_history.append(match_info)
        if len(self.match_history) > 6:
            self.match_history.pop(0)

        # Evaluate last 3 matches: require at least 2 RED tier matches for this suspect
        recent = self.match_history[-3:]
        red_matches = [m for m in recent if m["entry_id"] == entry_id and m["tier"] == "RED"]
        
        if len(red_matches) >= 2 or self.identity_locked:
            self.identity_locked = True
            self.identity = {
                "entry_id": entry_id,
                "name": name,
                "score": max(score, self.identity["score"] if self.identity else score),
                "tier": "RED",
                "locked": True,
            }
            return True

        if tier == "AMBER" and not self.identity_locked:
            self.identity = {
                "entry_id": entry_id,
                "name": name,
                "score": score,
                "tier": "AMBER",
                "locked": False,
            }

        return self.identity_locked


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

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 30) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.tracks: dict[int, Track] = {}
        self._next_id = 1
        self.stream_epoch = 0
        self.smoothing = 0.35

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
        unmatched_dets: list[dict[str, Any]] = []

        # Stage 1: match same class with IoU
        for det in detections:
            bbox = det["bbox_norm"]
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
                previous = trk.bbox_norm
                trk.bbox_norm = tuple(
                    (1.0 - self.smoothing) * old + self.smoothing * new
                    for old, new in zip(previous, bbox)
                )  # type: ignore[assignment]
                trk.confidence = float(det["confidence"])
                trk.age = 0
                trk.hits += 1
                trk.last_seen = timestamp
                trk.trajectory.append(trk.center)
                if len(trk.trajectory) > 64:
                    trk.trajectory.pop(0)
                matched.add(best_id)
            else:
                unmatched_dets.append(det)

        # Stage 2: Cross-class spatial overlap deduplication
        # If an unmatched detection heavily overlaps an existing active track (IoU > 0.40),
        # it is the exact same physical object classified as a different class (e.g. car vs motorcycle/person).
        for det in unmatched_dets:
            bbox = det["bbox_norm"]
            conf = float(det["confidence"])
            overlapping_tid: int | None = None
            best_overlap_iou = 0.40
            for tid, trk in self.tracks.items():
                iou = _iou(trk.bbox_norm, bbox)
                if iou > best_overlap_iou:
                    best_overlap_iou = iou
                    overlapping_tid = tid

            if overlapping_tid is not None:
                trk = self.tracks[overlapping_tid]
                # If new detection has higher confidence, promote its class
                if conf > trk.confidence:
                    trk.class_name = det["class_name"]
                    trk.class_id = int(det["class_id"])
                    trk.confidence = conf
                    trk.age = 0
                    trk.hits += 1
                    trk.last_seen = timestamp
                # Suppress creating a duplicate track
                continue

            # Stage 3: Truly new distinct object
            tid = self._next_id
            self._next_id += 1
            trk = Track(
                track_id=tid,
                class_name=det["class_name"],
                class_id=int(det["class_id"]),
                bbox_norm=bbox,
                confidence=conf,
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

        # Only return visible active tracks (age <= 2) to eliminate lingering ghost boxes
        visible_tracks = [t for t in self.tracks.values() if t.age <= 2]
        return visible_tracks, new_entries, terminated
