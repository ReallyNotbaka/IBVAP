"""Keeps IDs on boxes across frames. Simple centroid matcher for now.

Matches new detections to old tracks by distance, ages out ones that vanish.
footpoint (bottom-center) is what the fence check uses. record_biometric_match
handles the watchlist latch - critical locks right away, others need 2-of-3.
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
    prev_bbox_norm: tuple[float, float, float, float] | None = None
    synthetic: bool = False  # True when the box was projected from a face (no YOLO body evidence)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_norm
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def footpoint(self) -> tuple[float, float]:
        # bottom-center per spec 11 for person/vehicle zone logic
        x1, y1, x2, y2 = self.bbox_norm
        return ((x1 + x2) / 2.0, y2)

    @property
    def prev_footpoint(self) -> tuple[float, float] | None:
        if self.prev_bbox_norm is None:
            return None
        x1, y1, x2, y2 = self.prev_bbox_norm
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

        # Evaluate last 3 matches: require at least 2 RED tier matches for this suspect.
        # Count without building an intermediate list (hot on face frames).
        red_count = 0
        for m in self.match_history[-3:]:
            if m["entry_id"] == entry_id and m["tier"] == "RED":
                red_count += 1
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
            # AMBER matches NEVER overwrite a locked identity.
            # Return False: this entry_id is not the locked identity, so the
            # caller must not credit a sighting to it.
            if tier != "RED":
                return False

            # If currently locked to a CRITICAL target, non-critical matches cannot overwrite
            if curr_threat == "CRITICAL" and not is_critical:
                return False

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
            if red_count >= 2 and score > self.identity.get("score", 0.0):
                self.identity = {
                    "entry_id": entry_id,
                    "name": name,
                    "score": score,
                    "tier": "RED",
                    "threat_level": tl_str,
                    "locked": True,
                }
                return True

            # Locked to a different identity and no override: do not confirm B.
            return False

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
        if red_count >= 2:
            self.identity_locked = True
            prev_score = self.identity["score"] if (self.identity and self.identity.get("entry_id") == entry_id) else score
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
        self.smoothing = 0.35

    def reset_epoch(self, new_epoch: int) -> None:
        self.stream_epoch = new_epoch
        self.tracks.clear()
        self._next_id = 1

    def update(self, detections: list[dict[str, Any]], timestamp: float) -> tuple[list[Track], list[Track], list[Track]]:
        """Update with detections. Returns (all_tracks, new_entries, terminated).

        detections: list of {bbox_norm, class_name, class_id, confidence, synthetic?}
        """
        # age existing
        for t in self.tracks.values():
            t.age += 1

        matched: set[int] = set()
        new_entries: list[Track] = []
        unmatched_dets: list[dict[str, Any]] = []

        iou_threshold = self.iou_threshold
        smooth = self.smoothing
        inv_smooth = 1.0 - smooth
        iou_fn = _iou
        # Snapshot + precomputed centers: avoids re-iterating the dict and
        # recomputing trk.center per (det, track) pair. Centers of matched
        # tracks go stale, but matched ids are skipped afterwards, so this
        # is exactly equivalent.
        track_items = list(self.tracks.items())
        track_centers: list[tuple[int, Track, float, float]] = [
            (tid, trk, (trk.bbox_norm[0] + trk.bbox_norm[2]) / 2.0, (trk.bbox_norm[1] + trk.bbox_norm[3]) / 2.0) for tid, trk in track_items
        ]

        # Stage 1: match same class with IoU (with centroid proximity fallback for fast motion)
        for det in detections:
            if not track_items:
                unmatched_dets.append(det)
                continue
            bbox = det["bbox_norm"]
            det_class = det["class_name"]
            best_id: int | None = None
            best_iou = iou_threshold
            for tid, trk in track_items:
                if tid in matched:
                    continue
                if trk.class_name != det_class:
                    continue
                iou = iou_fn(trk.bbox_norm, bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_id = tid

            # Centroid proximity fallback for same class if box shifted quickly
            if best_id is None:
                det_cx = (bbox[0] + bbox[2]) / 2.0
                det_cy = (bbox[1] + bbox[3]) / 2.0
                best_dist = 0.14
                for tid, trk, trk_cx, trk_cy in track_centers:
                    if tid in matched:
                        continue
                    if trk.class_name != det_class:
                        continue
                    dist = ((det_cx - trk_cx) ** 2 + (det_cy - trk_cy) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_id = tid

            if best_id is not None:
                trk = self.tracks[best_id]
                trk.prev_bbox_norm = trk.bbox_norm
                previous = trk.bbox_norm
                # Explicit 4-float lerp: same math, no generator/zip alloc.
                trk.bbox_norm = (
                    inv_smooth * previous[0] + smooth * bbox[0],
                    inv_smooth * previous[1] + smooth * bbox[1],
                    inv_smooth * previous[2] + smooth * bbox[2],
                    inv_smooth * previous[3] + smooth * bbox[3],
                )
                trk.confidence = float(det["confidence"])
                # Provenance follows the evidence: a real detection clears the
                # face-anchored flag, a virtual re-hit keeps it.
                trk.synthetic = bool(det.get("synthetic", False))
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
        # If an unmatched detection heavily overlaps an existing active track (IoU > 0.60),
        # it is the exact same physical object classified as a different class (e.g. car vs motorcycle/person).
        for det in unmatched_dets:
            bbox = det["bbox_norm"]
            conf = float(det["confidence"])
            overlapping_tid: int | None = None
            best_overlap_iou = 0.60
            # Snapshot iteration: tracks spawned below are added to `matched`
            # immediately, so excluding them here is exactly equivalent.
            for tid, trk in track_items:
                if tid in matched:
                    continue
                iou = iou_fn(trk.bbox_norm, bbox)
                if iou > best_overlap_iou:
                    best_overlap_iou = iou
                    overlapping_tid = tid

            if overlapping_tid is not None:
                trk = self.tracks[overlapping_tid]
                has_person_identity = trk.class_name == "person" and (getattr(trk, "identity", None) is not None or getattr(trk, "identity_locked", False))
                if conf > trk.confidence and not (has_person_identity and det["class_name"] != "person"):
                    trk.class_name = det["class_name"]
                    trk.class_id = int(det["class_id"])
                trk.confidence = max(trk.confidence, conf)
                trk.age = 0
                trk.hits += 1
                trk.last_seen = timestamp
                trk.prev_bbox_norm = trk.bbox_norm
                previous = trk.bbox_norm
                # Explicit 4-float lerp: same math, no generator/zip alloc.
                trk.bbox_norm = (
                    inv_smooth * previous[0] + smooth * bbox[0],
                    inv_smooth * previous[1] + smooth * bbox[1],
                    inv_smooth * previous[2] + smooth * bbox[2],
                    inv_smooth * previous[3] + smooth * bbox[3],
                )
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
                synthetic=bool(det.get("synthetic", False)),
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

        # Preserve confirmed and locked tracks through short detector misses,
        # but suppress ghost duplicates if an active track (age == 0) overlaps an aged track.
        active_boxes = [t.bbox_norm for t in self.tracks.values() if t.age == 0]
        visible_tracks: list[Track] = []
        for t in self.tracks.values():
            max_allowed_age = 12 if t.identity_locked and t.identity and t.identity.get("threat_level") == "CRITICAL" else 3
            if t.age > max_allowed_age:
                continue
            if t.age > 0 and active_boxes:
                t_box = t.bbox_norm
                if any(iou_fn(t_box, act_box) > 0.25 for act_box in active_boxes):
                    continue
            visible_tracks.append(t)
        return visible_tracks, new_entries, terminated
