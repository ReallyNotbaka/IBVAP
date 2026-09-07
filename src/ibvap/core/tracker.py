"""Simple centroid tracker - ByteTrack stub for Phase 3 slice.

Spec 12: ByteTrack as initial tracker; Phase 3 uses this minimal centroid tracker
to prove ID persistence within camera+epoch without heavy supervision deps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ibvap.core.watchlist import ThreatLevel


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
    last_bio_frame: int = -999

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
        threat_level: str | ThreatLevel = ThreatLevel.HIGH,
    ) -> bool:
        """Record face recognition match and apply temporal confirmation latch.
        
        - Critical targets (ThreatLevel.CRITICAL) lock immediately on RED tier match.
        - Other suspects lock on 2-of-3 RED matches or retain existing lock.
        - Sets identity immediately so UI displays target name and red box from frame 1.
        Returns True if identity is confirmed and locked.
        """
        tl_str = threat_level.value if hasattr(threat_level, "value") else str(threat_level).upper()
        match_info = {
            "entry_id": entry_id,
            "name": name,
            "score": score,
            "tier": tier,
            "threat_level": tl_str,
        }
        self.match_history.append(match_info)
        if len(self.match_history) > 6:
            self.match_history.pop(0)

        # Evaluate last 3 matches: require at least 2 RED tier matches for this suspect
        recent = self.match_history[-3:]
        red_matches = [m for m in recent if m["entry_id"] == entry_id and m["tier"] == "RED"]
        is_critical = tl_str == "CRITICAL"

        # If already locked to an identity:
        if self.identity_locked and self.identity:
            curr_entry_id = self.identity.get("entry_id")
            curr_threat = self.identity.get("threat_level", "HIGH")

            # Same suspect: maintain lock and update peak score
            if curr_entry_id == entry_id:
                if tier == "RED":
                    self.identity["score"] = max(self.identity["score"], score)
                return True

            # Different suspect: protect the existing locked identity!
            # AMBER matches NEVER overwrite a locked identity
            if tier != "RED":
                return True

            # If currently locked to a CRITICAL target, non-critical matches cannot overwrite
            if curr_threat == "CRITICAL" and not is_critical:
                return True

            # Precedence: CRITICAL target incoming over non-critical locked target
            if is_critical and curr_threat != "CRITICAL":
                self.identity = {
                    "entry_id": entry_id,
                    "name": name,
                    "score": score,
                    "tier": "RED",
                    "threat_level": tl_str,
                    "locked": True,
                }
                return True

            # Both same tier: require 2 RED matches and strictly higher score to reassign
            if len(red_matches) >= 2 and score > self.identity.get("score", 0.0):
                self.identity = {
                    "entry_id": entry_id,
                    "name": name,
                    "score": score,
                    "tier": "RED",
                    "threat_level": tl_str,
                    "locked": True,
                }
                return True

            return True

        # Not locked yet:
        # Critical target locks immediately on first RED tier match
        if is_critical and tier == "RED":
            self.identity_locked = True
            self.identity = {
                "entry_id": entry_id,
                "name": name,
                "score": score,
                "tier": "RED",
                "threat_level": tl_str,
                "locked": True,
            }
            return True

        # Non-critical suspect confirmed on 2 of 3 RED matches
        if len(red_matches) >= 2:
            self.identity_locked = True
            prev_score = (
                self.identity["score"]
                if (self.identity and self.identity.get("entry_id") == entry_id)
                else score
            )
            self.identity = {
                "entry_id": entry_id,
                "name": name,
                "score": max(score, prev_score),
                "tier": "RED",
                "threat_level": tl_str,
                "locked": True,
            }
            return True

        # First RED match of non-critical target: set tentative identity immediately
        if tier == "RED":
            # Don't overwrite an existing tentative CRITICAL match with a non-critical match
            if self.identity and self.identity.get("threat_level") == "CRITICAL" and not is_critical:
                return False

            self.identity = {
                "entry_id": entry_id,
                "name": name,
                "score": score,
                "tier": "RED",
                "threat_level": tl_str,
                "locked": False,
            }
            return False

        # AMBER match: only set if no RED identity exists yet
        if tier == "AMBER" and not self.identity:
            self.identity = {
                "entry_id": entry_id,
                "name": name,
                "score": score,
                "tier": "AMBER",
                "threat_level": tl_str,
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

    def __init__(self, iou_threshold: float = 0.20, max_age: int = 30) -> None:
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.tracks: dict[int, Track] = {}
        self._next_id = 1
        self.stream_epoch = 0
        self.smoothing = 0.65

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

        # Stage 1: match same class with IoU (with centroid proximity fallback for fast motion)
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

            # Centroid proximity fallback for same class if box shifted quickly
            if best_id is None:
                det_cx = (bbox[0] + bbox[2]) / 2.0
                det_cy = (bbox[1] + bbox[3]) / 2.0
                best_dist = 0.14
                for tid, trk in self.tracks.items():
                    if tid in matched:
                        continue
                    if trk.class_name != det["class_name"]:
                        continue
                    trk_cx, trk_cy = trk.center
                    dist = ((det_cx - trk_cx) ** 2 + (det_cy - trk_cy) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
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
                has_person_identity = (
                    trk.class_name == "person"
                    and (getattr(trk, "identity", None) is not None or getattr(trk, "identity_locked", False))
                )
                if conf > trk.confidence and not (has_person_identity and det["class_name"] != "person"):
                    trk.class_name = det["class_name"]
                    trk.class_id = int(det["class_id"])
                trk.confidence = max(trk.confidence, conf)
                trk.age = 0
                trk.hits += 1
                trk.last_seen = timestamp
                previous = trk.bbox_norm
                trk.bbox_norm = tuple(
                    (1.0 - self.smoothing) * old + self.smoothing * new
                    for old, new in zip(previous, bbox)
                )  # type: ignore[assignment]
                trk.trajectory.append(trk.center)
                if len(trk.trajectory) > 64:
                    trk.trajectory.pop(0)
                matched.add(overlapping_tid)
                continue

            # Stage 3: Truly new distinct object
            # Suppress spurious low-confidence detections from creating new tracks
            min_spawn = 0.50 if det.get("class_name") == "person" else 0.40
            if conf < min_spawn:
                continue

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
            trk = self.tracks[tid]
            # Fast drop unconfirmed 1-hit tracks (glitches) within 3 frames; confirmed tracks use max_age
            drop_limit = 3 if trk.hits <= 1 else self.max_age
            if trk.age > drop_limit:
                terminated.append(self.tracks.pop(tid))

        # Only return visible active tracks (age <= 2) to eliminate lingering ghost boxes
        visible_tracks = [t for t in self.tracks.values() if t.age <= 2]
        return visible_tracks, new_entries, terminated
