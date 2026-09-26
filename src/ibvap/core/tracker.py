"""Keeps IDs on boxes across frames. Simple centroid matcher for now.

Matches new detections to old tracks by distance, ages out ones that vanish.
footpoint (bottom-center) is what the fence check uses. record_biometric_match
handles the watchlist latch - critical locks right away, others need 2-of-3.
"""

from __future__ import annotations

import math
from collections import deque
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
    trajectory: Any = field(default_factory=lambda: deque(maxlen=64))
    identity: dict[str, Any] | None = None
    identity_locked: bool = False
    match_history: list[dict[str, Any]] = field(default_factory=list)
    last_bio_frame: int = -999
    prev_bbox_norm: tuple[float, float, float, float] | None = None
    synthetic: bool = False  # True when the box was projected from a face (no YOLO body evidence)
    is_intrusion: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.trajectory, deque) or getattr(self.trajectory, "maxlen", None) != 64:
            self.trajectory = deque(self.trajectory, maxlen=64)

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


def _sanitize_bbox(bbox: Any, class_name: str | None = None) -> tuple[float, float, float, float] | None:
    """Sanitize and validate normalized bounding box coordinates [x1, y1, x2, y2].

    - Rejects non-iterable, wrong length, or non-finite (NaN/Inf) values.
    - Corrects inverted coordinates (x1 > x2 or y1 > y2).
    - Clamps coordinates to [0.0, 1.0].
    - Rejects degenerate boxes (width < 0.005 or height < 0.005).
    - Rejects unviable human aspect ratios for 'person' class.
    """
    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None

    if not (math.isfinite(x1) and math.isfinite(y1) and math.isfinite(x2) and math.isfinite(y2)):
        return None
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    x2 = max(0.0, min(1.0, x2))
    y2 = max(0.0, min(1.0, y2))
    bw = x2 - x1
    bh = y2 - y1
    if bw < 0.005 or bh < 0.005:
        return None
    if class_name == "person":
        hw_ratio = bh / max(1e-5, bw)
        if hw_ratio < 0.15 or hw_ratio > 7.5:
            return None
    return (x1, y1, x2, y2)


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

        iou_threshold = self.iou_threshold
        smooth = self.smoothing
        inv_smooth = 1.0 - smooth
        iou_fn = _iou
        for trk in self.tracks.values():
            trk.is_intrusion = False
        track_items = list(self.tracks.items())
        track_centers: list[tuple[int, Track, float, float]] = [
            (tid, trk, (trk.bbox_norm[0] + trk.bbox_norm[2]) / 2.0, (trk.bbox_norm[1] + trk.bbox_norm[3]) / 2.0) for tid, trk in track_items
        ]

        # Sanitize incoming detection bounding boxes
        valid_detections: list[dict[str, Any]] = []
        for det in detections:
            clean_box = _sanitize_bbox(det.get("bbox_norm"), det.get("class_name"))
            if clean_box is None:
                continue
            det_clean = dict(det)
            det_clean["bbox_norm"] = clean_box
            valid_detections.append(det_clean)
        detections = valid_detections

        # Deduplicate incoming detections of the same class (intra-frame NMS & sub-box suppression)
        # Sort by area descending so full-body enclosing boxes are evaluated before partial sub-boxes
        # (e.g. torso inside full-body). This ensures sub-boxes never discard full-body boxes!
        if len(detections) > 1:
            filtered_dets: list[dict[str, Any]] = []
            sorted_dets = sorted(
                detections,
                key=lambda d: (
                    (d["bbox_norm"][2] - d["bbox_norm"][0]) * (d["bbox_norm"][3] - d["bbox_norm"][1]),
                    float(d.get("confidence", 0.0)),
                ),
                reverse=True,
            )
            for det in sorted_dets:
                bbox = det["bbox_norm"]
                cls_name = det.get("class_name")
                conf = float(det.get("confidence", 0.0))
                area_b = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                is_dup = False
                for kept in filtered_dets:
                    if kept.get("class_name") == cls_name:
                        kb = kept["bbox_norm"]
                        iou_val = iou_fn(bbox, kb)
                        if iou_val > 0.85:
                            is_dup = True
                            kept["confidence"] = max(float(kept.get("confidence", 0.0)), conf)
                            break
                        ix1, iy1 = max(bbox[0], kb[0]), max(bbox[1], kb[1])
                        ix2, iy2 = min(bbox[2], kb[2]), min(bbox[3], kb[3])
                        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                        # Containment check: det is contained inside kept (which has >= area)
                        if area_b > 0 and (inter / area_b) > 0.90:
                            is_dup = True
                            kept["confidence"] = max(float(kept.get("confidence", 0.0)), conf)
                            break
                if not is_dup:
                    filtered_dets.append(det)
            detections = filtered_dets

        # Stage 1: Global maximum-IoU bipartite matching for same-class objects.
        # Sorting all (iou, det_idx, tid) candidates by IoU descending guarantees that
        # detections with the highest spatial overlap claim their tracks first.
        matched_det_indices: set[int] = set()
        iou_candidates: list[tuple[float, int, int]] = []
        if track_items:
            for det_idx, det in enumerate(detections):
                bbox = det["bbox_norm"]
                det_class = det["class_name"]
                for tid, trk in track_items:
                    if trk.class_name != det_class:
                        continue
                    iou = iou_fn(trk.bbox_norm, bbox)
                    if iou > iou_threshold:
                        iou_candidates.append((iou, det_idx, tid))

            iou_candidates.sort(key=lambda c: c[0], reverse=True)
            for _iou_val, det_idx, tid in iou_candidates:
                if det_idx in matched_det_indices or tid in matched:
                    continue
                matched_det_indices.add(det_idx)
                matched.add(tid)
                det = detections[det_idx]
                bbox = det["bbox_norm"]
                trk = self.tracks[tid]
                trk.prev_bbox_norm = trk.bbox_norm
                previous = trk.bbox_norm
                trk.bbox_norm = (
                    inv_smooth * previous[0] + smooth * bbox[0],
                    inv_smooth * previous[1] + smooth * bbox[1],
                    inv_smooth * previous[2] + smooth * bbox[2],
                    inv_smooth * previous[3] + smooth * bbox[3],
                )
                trk.confidence = float(det["confidence"])
                trk.synthetic = bool(det.get("synthetic", False))
                trk.age = 0
                trk.hits += 1
                trk.last_seen = timestamp
                trk.trajectory.append(trk.center)

            # Centroid proximity fallback for same-class fast motion among remaining unmatched
            remaining_det_indices = [i for i in range(len(detections)) if i not in matched_det_indices]
            if remaining_det_indices and len(matched) < len(track_items):
                dist_candidates: list[tuple[float, int, int]] = []
                for det_idx in remaining_det_indices:
                    det = detections[det_idx]
                    bbox = det["bbox_norm"]
                    det_class = det["class_name"]
                    det_cx = (bbox[0] + bbox[2]) / 2.0
                    det_cy = (bbox[1] + bbox[3]) / 2.0
                    for tid, trk, trk_cx, trk_cy in track_centers:
                        if tid in matched or trk.class_name != det_class:
                            continue
                        dist = ((det_cx - trk_cx) ** 2 + (det_cy - trk_cy) ** 2) ** 0.5
                        if dist < 0.14:
                            dist_candidates.append((dist, det_idx, tid))

                dist_candidates.sort(key=lambda c: c[0])
                for _dist_val, det_idx, tid in dist_candidates:
                    if det_idx in matched_det_indices or tid in matched:
                        continue
                    matched_det_indices.add(det_idx)
                    matched.add(tid)
                    det = detections[det_idx]
                    bbox = det["bbox_norm"]
                    trk = self.tracks[tid]
                    trk.prev_bbox_norm = trk.bbox_norm
                    previous = trk.bbox_norm
                    trk.bbox_norm = (
                        inv_smooth * previous[0] + smooth * bbox[0],
                        inv_smooth * previous[1] + smooth * bbox[1],
                        inv_smooth * previous[2] + smooth * bbox[2],
                        inv_smooth * previous[3] + smooth * bbox[3],
                    )
                    trk.confidence = float(det["confidence"])
                    trk.synthetic = bool(det.get("synthetic", False))
                    trk.age = 0
                    trk.hits += 1
                    trk.last_seen = timestamp
                    trk.trajectory.append(trk.center)

        unmatched_dets = [detections[i] for i in range(len(detections)) if i not in matched_det_indices]

        # Stage 2: Spatial overlap deduplication for unmatched detections
        # If an unmatched detection heavily overlaps an already matched track (same-class or cross-class),
        # it is a duplicate detection ("duplicate boxes") of that active physical object - discard it.
        # If it heavily overlaps an UNMATCHED track (IoU > 0.60), re-associate/update that track (cross-class).
        surviving_unmatched: list[dict[str, Any]] = []
        for det in unmatched_dets:
            bbox = det["bbox_norm"]
            conf = float(det["confidence"])
            det_class = det.get("class_name")
            area_b = max(1e-5, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            is_dup = False
            overlapping_unmatched_tid: int | None = None
            best_overlap_iou = 0.60

            for tid, trk in track_items:
                iou = iou_fn(trk.bbox_norm, bbox)
                area_t = max(1e-5, (trk.bbox_norm[2] - trk.bbox_norm[0]) * (trk.bbox_norm[3] - trk.bbox_norm[1]))
                ix1, iy1 = max(bbox[0], trk.bbox_norm[0]), max(bbox[1], trk.bbox_norm[1])
                ix2, iy2 = min(bbox[2], trk.bbox_norm[2]), min(bbox[3], trk.bbox_norm[3])
                inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                containment = inter / min(area_b, area_t)

                if tid in matched:
                    if (trk.class_name == det_class and (iou > 0.85 or containment > 0.90)) or (trk.class_name != det_class and iou > 0.60):
                        is_dup = True
                        break
                else:
                    if iou > best_overlap_iou:
                        best_overlap_iou = iou
                        overlapping_unmatched_tid = tid

            if is_dup:
                continue

            if overlapping_unmatched_tid is not None:
                trk = self.tracks[overlapping_unmatched_tid]
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
                trk.bbox_norm = (
                    inv_smooth * previous[0] + smooth * bbox[0],
                    inv_smooth * previous[1] + smooth * bbox[1],
                    inv_smooth * previous[2] + smooth * bbox[2],
                    inv_smooth * previous[3] + smooth * bbox[3],
                )
                trk.trajectory.append(trk.center)
                matched.add(overlapping_unmatched_tid)
                continue

            surviving_unmatched.append(det)

        unmatched_dets = surviving_unmatched

        # Stage 3: Truly new distinct object
        # Suppress spurious low-confidence detections from creating new tracks
        for det in unmatched_dets:
            bbox = det["bbox_norm"]
            conf = float(det["confidence"])
            det_class = det.get("class_name")
            min_spawn = 0.50 if det_class == "person" else 0.40
            if conf < min_spawn:
                continue
            # Suppress if this detection duplicates a newly spawned track in this frame
            if any(iou_fn(bbox, n_trk.bbox_norm) > 0.60 for n_trk in new_entries):
                continue
            # Suppress if this detection heavily overlaps any already active track (age == 0)
            area_b = max(1e-5, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            duplicate_active = False
            for t in self.tracks.values():
                if t.age == 0:
                    iou = iou_fn(bbox, t.bbox_norm)
                    area_t = max(1e-5, (t.bbox_norm[2] - t.bbox_norm[0]) * (t.bbox_norm[3] - t.bbox_norm[1]))
                    ix1, iy1 = max(bbox[0], t.bbox_norm[0]), max(bbox[1], t.bbox_norm[1])
                    ix2, iy2 = min(bbox[2], t.bbox_norm[2]), min(bbox[3], t.bbox_norm[3])
                    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
                    containment = inter / min(area_b, area_t)
                    if (t.class_name == det_class and (iou > 0.85 or containment > 0.90)) or (t.class_name != det_class and iou > 0.60):
                        duplicate_active = True
                        break
            if duplicate_active:
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
                trajectory=deque([((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)], maxlen=64),
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

        # Strict camera-wide watchlist identity mutual exclusivity across tracks:
        # Under NO circumstances can two tracks simultaneously hold the same entry_id.
        seen_entries: dict[str, Track] = {}
        for trk in list(self.tracks.values()):
            if trk.identity and trk.identity.get("entry_id"):
                eid = trk.identity["entry_id"]
                if eid in seen_entries:
                    prev = seen_entries[eid]
                    prev_active = prev.age == 0
                    curr_active = trk.age == 0
                    prev_locked = getattr(prev, "identity_locked", False)
                    curr_locked = getattr(trk, "identity_locked", False)
                    prev_crit = (getattr(prev, "identity", None) or {}).get("threat_level") == "CRITICAL"
                    curr_crit = (getattr(trk, "identity", None) or {}).get("threat_level") == "CRITICAL"
                    prev_score = float(prev.identity.get("score", 0.0))
                    curr_score = float(trk.identity.get("score", 0.0))

                    if curr_locked and not prev_locked:
                        trk_wins = True
                    elif prev_locked and not curr_locked:
                        trk_wins = False
                    elif curr_crit and not prev_crit:
                        trk_wins = True
                    elif prev_crit and not curr_crit:
                        trk_wins = False
                    elif curr_active and not prev_active:
                        trk_wins = True
                    elif prev_active and not curr_active:
                        trk_wins = False
                    elif curr_score > prev_score:
                        trk_wins = True
                    elif curr_score < prev_score:
                        trk_wins = False
                    else:
                        trk_wins = trk.hits > prev.hits

                    if trk_wins:
                        prev.identity = None
                        prev.identity_locked = False
                        seen_entries[eid] = trk
                    else:
                        trk.identity = None
                        trk.identity_locked = False
                else:
                    seen_entries[eid] = trk

        # Preserve confirmed and locked tracks through short detector misses,
        # but suppress ghost duplicates if an active track (age == 0) overlaps an aged non-critical track.
        active_boxes = [t.bbox_norm for t in self.tracks.values() if t.age == 0]
        visible_tracks: list[Track] = []
        for t in self.tracks.values():
            is_crit = bool(t.identity_locked and t.identity and t.identity.get("threat_level") == "CRITICAL")
            max_allowed_age = 12 if is_crit else (2 if (t.hits >= 2 or getattr(t, "identity_locked", False)) else 1)
            if t.age > max_allowed_age:
                continue
            if t.age > 0 and active_boxes and not is_crit:
                # Do NOT suppress confirmed critical targets during their occlusion grace period!
                t_box = t.bbox_norm
                if any(iou_fn(t_box, act_box) > 0.35 for act_box in active_boxes):
                    continue
            visible_tracks.append(t)

        # Guarantee visible_tracks contains at most one track per watchlist entry
        seen_vis: set[str] = set()
        clean_visible: list[Track] = []
        for t in visible_tracks:
            eid = t.identity.get("entry_id") if t.identity else None
            if eid:
                if eid in seen_vis:
                    continue
                seen_vis.add(eid)
            clean_visible.append(t)
        return clean_visible, new_entries, terminated
