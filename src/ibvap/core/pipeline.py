"""Per-camera analytics pipeline. One of these runs for each connected camera.

Frame in -> YOLO detect + face -> track (face-only detections anchor virtual
person boxes) -> zone check -> event out.
Queues are bounded (size 2) so if inference lags we drop old frames instead
of building up delay. sample_stride skips detector on some frames, face_stride
skips YuNet even more - keeps it realtime on weak edge boxes.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from ibvap.core.association import (
    _box_iou,
    associate_faces_to_tracks,
    link_synthetic_tracks,
    project_person_box_from_face,
)
from ibvap.core.detector import DetectorProvider, MockPersonDetector, ONNXDetectorProvider
from ibvap.core.queue import BoundedQueue
from ibvap.core.rules import RuleEngine
from ibvap.core.tracker import CentroidTracker
from ibvap.core.watchlist import get_watchlist_store
from ibvap.core.zone_engine import DEFAULT_ZONE, Zone, is_intrusion
from ibvap.events.outbox import transactional_write

# Lazy import type for face to avoid circular heavy init at import time
try:
    from ibvap.core.face import FaceDetector as _FaceDetector  # type: ignore

    _FaceDetectorType = _FaceDetector
except Exception:  # pragma: no cover
    _FaceDetectorType = None  # type: ignore


class MiniPipeline:
    """Camera-scoped pipeline - proves E2E slice with ONNX detector or mock detector."""

    def __init__(
        self,
        camera_id: str,
        stream_epoch: int = 0,
        detector: DetectorProvider | None = None,
        detector_handle: object | None = None,
        face_detector: object | None = None,
        face_recognizer: object | None = None,
        enable_face: bool = True,
        face_stride: int = 3,
        sample_stride: int = 1,
        max_face_size: int | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.stream_epoch = stream_epoch
        self.detector_handle = detector_handle
        if detector is not None:
            self.detector = detector
        elif Path("models/yolo26n.onnx").exists():
            self.detector = ONNXDetectorProvider("models/yolo26n.onnx")
        else:
            self.detector = MockPersonDetector()
        self.tracker = CentroidTracker()
        self.tracker.stream_epoch = stream_epoch
        self.zone = DEFAULT_ZONE
        self.rule_engine = RuleEngine(loiter_seconds=10.0, cooldown_seconds=10.0)
        # bounded queues per spec 10
        self.q_demux_to_sample = BoundedQueue("demux->sample", max_size=2, max_age_ms=400)
        self.q_sample_to_infer = BoundedQueue("sample->infer", max_size=2, max_age_ms=400)
        self.frame_idx = 0
        self.events_created = 0
        self.alerted_tracks: set[int] = set()
        self.watchlist_alerted_tracks: set[int] = set()
        self._active_line_intruders: set[int] = set()
        self._track_outside_count: dict[int, int] = {}
        # Consecutive frames an alerted track went unseen (T3 visibility gate).
        self._unseen_streak: dict[int, int] = {}
        self._line_miss_count: dict[int, int] = {}
        self._last_intrusion_alert_time: dict[tuple[str, int], float] = {}
        self._last_exit_alert_time: dict[int, float] = {}
        self.last_detections: list[dict] = []
        self.last_tracks: list = []
        # --- face optimisation ---
        self.sample_stride = max(1, sample_stride)
        self.face_stride = max(1, face_stride)
        self.max_face_size = max_face_size
        self.enable_face = enable_face
        # Lazy face detector init - reuse model's Zoo weights, do not re-download
        if face_detector is not None:
            self.face_detector = face_detector  # injected (or mock)
        elif enable_face and _FaceDetectorType is not None and Path("models/face_detection_yunet_2023mar.onnx").exists():
            try:
                self.face_detector = _FaceDetectorType()  # type: ignore[operator]
            except Exception:
                self.face_detector = None
        else:
            self.face_detector = None

        if face_recognizer is not None:
            self.face_recognizer = face_recognizer
        elif enable_face and Path("models/face_recognition_sface_2021dec.onnx").exists():
            try:
                from ibvap.core.face import FaceRecognizer

                self.face_recognizer = FaceRecognizer()
            except Exception:
                self.face_recognizer = None
        else:
            self.face_recognizer = None

        self.last_faces: list[dict] = []
        self.faces_analyzed = 0
        self.frames_skipped = 0
        # Cache key for the rule-engine zone mirror (rebuilt only on change).
        self._rule_zone_id: str | None = None

    def reset_epoch(self, new_epoch: int) -> None:
        """Reset stream epoch and clear all per-track alert/latch state."""
        self.stream_epoch = new_epoch
        self.tracker.reset_epoch(new_epoch)
        self.rule_engine.reset()
        self.alerted_tracks.clear()
        self.watchlist_alerted_tracks.clear()
        self._active_line_intruders.clear()
        self._track_outside_count.clear()
        self._line_miss_count.clear()
        self._last_intrusion_alert_time.clear()
        self._last_exit_alert_time.clear()
        self._unseen_streak.clear()

    def _end_presence_event(
        self,
        *,
        track_id: int,
        bbox_norm: tuple[float, float, float, float],
        confidence: float,
        camera_id: str,
        stream_epoch: int,
        zone: Zone,
        zone_id: str,
        zone_name: str,
        is_line_zone: bool,
        model_id: str,
        now_ts: float,
    ) -> dict | None:
        """Build the presence-end event for a track gone dark (or purged).

        Last-known position decides, without trajectory memory: foot outside
        -> zone_exit, foot inside -> target_lost (standing down an active
        intruder as "exited" would be wrong). None when debounced. Callers
        persist the returned dict and count it.
        """
        foot = ((bbox_norm[0] + bbox_norm[2]) / 2.0, bbox_norm[3])
        last_outside = not is_intrusion(foot, zone)
        last_exit = self._last_exit_alert_time.get((zone_id, track_id), 0.0)
        if (now_ts - last_exit) < 3.0:
            return None
        self._last_exit_alert_time[(zone_id, track_id)] = now_ts
        base = {
            "camera_id": camera_id,
            "stream_epoch": stream_epoch,
            "zone_id": zone_id,
            "track_id": track_id,
            "bbox_norm": bbox_norm,
            "confidence": confidence,
            "model_id": model_id,
        }
        if last_outside:
            rule_name = "tripwire_line_exit" if is_line_zone else "restricted_zone_exit"
            observed = f"track {track_id} exited line perimeter" if is_line_zone else f"track {track_id} exited restricted zone"
            threshold = "outside line perimeter" if is_line_zone else "outside restricted zone"
            return {
                **base,
                "event_type": "zone_exit",
                "explanation": {"rule": rule_name, "zone": zone_name, "observed": observed, "threshold": threshold},
            }
        return {
            **base,
            "event_type": "target_lost",
            "explanation": {
                "rule": "target_lost_in_zone",
                "zone": zone_name,
                "observed": f"track {track_id} lost inside restricted zone",
                "threshold": "last seen inside restricted zone",
            },
        }

    def process_frame(self, frame: np.ndarray) -> dict | None:
        """Run one frame through detect/track/face/zone. Returns event if something fired.

        Skips heavy work on stride frames to save time - keeps last results
        around so the UI doesn't flicker. Face runs even less often than YOLO
        since YuNet is pricey on big frames (we downscale to max_face_size first).
        """
        # ---- sampling optimisation: skip heavy inference for non-sampled frames ----
        if self.sample_stride > 1 and (self.frame_idx % self.sample_stride) != 0:
            self.frames_skipped += 1
            # Keep previous last_detections/last_faces visible to avoid flicker; tracker ages on next sampled frame
            self.frame_idx += 1
            return None

        # sampling queue - drop stale
        self.q_demux_to_sample.put(frame)
        latest = self.q_demux_to_sample.get_latest()
        if latest is None:
            return None
        # inference queue
        self.q_sample_to_infer.put(latest)  # type: ignore[arg-type]
        infer_frame = self.q_sample_to_infer.get_latest()
        if infer_frame is None:
            return None

        # detect (person/vehicle) on the queued infer_frame (bounded-queue sync path)
        if self.detector_handle is not None and hasattr(self.detector_handle, "acquire"):
            with self.detector_handle.acquire() as det:
                detections = det.detect(infer_frame, self.frame_idx)
                self.model_id = getattr(det, "model_id", "yolo26n")
                self.runtime = getattr(det, "runtime", "directml")
        else:
            detections = self.detector.detect(infer_frame, self.frame_idx)
            self.model_id = getattr(self.detector, "model_id", "yolo26n")
            self.runtime = getattr(self.detector, "runtime", "cpu")

        det_dicts = [
            {
                "bbox_norm": d.bbox_norm,
                "class_name": d.class_name,
                "class_id": d.class_id,
                "confidence": d.confidence,
            }
            for d in detections
        ]
        self.last_detections = det_dicts

        # ---- face detection (optimized, sampled) ----
        # Runs BEFORE tracking: orphan (face-only) detections are projected
        # to virtual person boxes below so the tracker holds them normally.
        # Retain previous faces across stride-skipped frames to avoid flicker; only update on sampled face frames
        new_faces_detected = False
        if self.enable_face and self.face_detector is not None:
            # Run YuNet only every face_stride sampled frames to save ~8ms per frame
            sampled_idx = self.frame_idx // self.sample_stride if self.sample_stride > 1 else self.frame_idx
            if (sampled_idx % self.face_stride) == 0:
                try:
                    # Native resolution processing (do not drop resolution for maximum detection accuracy)
                    fd_frame = infer_frame
                    if self.max_face_size is not None and self.max_face_size > 0:
                        h, w = infer_frame.shape[:2]
                        if max(h, w) > self.max_face_size:
                            scale = self.max_face_size / float(max(h, w))
                            nw, nh = int(w * scale), int(h * scale)
                            if nw > 0 and nh > 0:
                                fd_frame = cv2.resize(infer_frame, (nw, nh), interpolation=cv2.INTER_AREA)
                    raw_faces = self.face_detector.detect(fd_frame)  # type: ignore[union-attr]
                    self._last_face_frame = fd_frame
                    self.last_faces = [
                        {
                            "bbox_norm": f.bbox_norm,
                            "confidence": f.confidence,
                            "quality_passed": f.quality.passed,
                            "landmarks": f.landmarks,
                            "blur": f.quality.blur,
                            "illumination": f.quality.illumination,
                            "_raw": f,
                        }
                        for f in raw_faces
                    ]
                    self.faces_analyzed += 1
                    new_faces_detected = bool(self.last_faces)
                except Exception:
                    pass

        # ---- face-anchored fallback: virtual person box for orphan faces ----
        # Someone standing right in front of the camera shows a face but no
        # YOLO body box. Project an approximate body box so tracking, identity
        # latching, and zones keep working. Real detections always win: any
        # overlap with a person box suppresses synthesis for that face.
        if new_faces_detected:
            person_boxes = [d["bbox_norm"] for d in det_dicts if d.get("class_name") == "person"]
            for face_info in self.last_faces:
                if not face_info.get("quality_passed"):
                    continue
                fb = face_info["bbox_norm"]
                if any(_box_iou(fb, pb) > 0.0 for pb in person_boxes):
                    continue
                body = project_person_box_from_face(fb)
                if body is None:
                    continue
                det_dicts.append(
                    {
                        "bbox_norm": body,
                        "class_name": "person",
                        "class_id": 0,
                        "confidence": float(face_info.get("confidence", 0.5)),
                        "synthetic": True,
                    }
                )

        # Single clock read per frame shared by tracker + all debounce logic.
        now_ts = time.time()
        tracks, new_entries, terminated = self.tracker.update(det_dicts, timestamp=now_ts)
        self.last_tracks = tracks
        model_id = getattr(self, "model_id", "yolo26n")

        # ---- Hungarian Head-ROI track-to-face spatial fusion & biometric identification ----
        if new_faces_detected and self.last_faces and self.face_recognizer is not None:
            try:
                assignments = associate_faces_to_tracks(tracks, self.last_faces)
                # Provenance links for face-anchored tracks the gates cannot
                # see (extreme close-ups): fill only unassigned slots so the
                # Hungarian optimum for real tracks is never disturbed.
                for trk_id, face_info in link_synthetic_tracks(tracks, self.last_faces).items():
                    assignments.setdefault(trk_id, face_info)
                wl_store = get_watchlist_store()
                crop_frame = getattr(self, "_last_face_frame", infer_frame)
                track_by_id = {t.track_id: t for t in tracks}
                for trk_id, face_info in assignments.items():
                    target_track = track_by_id.get(trk_id)
                    if target_track is None:
                        continue
                    # Check locked state and threat level
                    is_locked = getattr(target_track, "identity_locked", False)
                    curr_threat = getattr(target_track, "identity", {}).get("threat_level") if target_track.identity else None
                    # If already locked to a CRITICAL target, identity cannot be overridden; skip redundant extraction
                    if is_locked and curr_threat == "CRITICAL":
                        continue
                    # For non-critical locked tracks, poll at a lower cadence (every 30 frames) to allow CRITICAL target override
                    # For unlocked tracks, check at most once every 6 frames
                    last_bio = getattr(target_track, "last_bio_frame", -999)
                    cadence = 30 if is_locked else 6
                    if last_bio >= 0 and (self.frame_idx - last_bio) < cadence:
                        continue
                    raw_f = face_info.get("_raw")
                    if raw_f is not None and getattr(getattr(raw_f, "quality", None), "passed", True):
                        target_track.last_bio_frame = self.frame_idx
                        aligned = self.face_recognizer.align_crop(crop_frame, raw_f)
                        feat = self.face_recognizer.extract_feature(aligned).flatten()
                        match = wl_store.identify(feat)
                        if match is not None:
                            confirmed = target_track.record_biometric_match(
                                entry_id=match.entry_id,
                                name=match.name,
                                score=match.score,
                                tier=match.tier,
                                threat_level=match.threat_level,
                            )
                            # Only credit the sighting if the track is locked
                            # to this entry_id (protects against A-locked/B-match).
                            if confirmed and target_track.identity and target_track.identity.get("entry_id") == match.entry_id:
                                wl_store.record_sighting(match.entry_id, time.time())
            except Exception:
                pass

        primary_event: dict | None = None
        intrusion_track_ids: set[int] = set()
        # Hoisted per-frame locals: avoids repeated attribute lookups and
        # getattr-with-default scans across the per-track event loops.
        camera_id = self.camera_id
        stream_epoch = self.stream_epoch
        zone = self.zone
        zone_id = zone.id
        zone_name = zone.name
        is_line_zone = getattr(zone, "is_line", False)
        if zone_id != DEFAULT_ZONE.id:
            # Mirror the active zone into the rule engine only when it changed,
            # instead of rebuilding the list/dict wrapper every frame. The
            # stored dict keeps a reference to the live polygon list, so
            # in-place edits stay visible; identity check catches reassignment.
            cached_zones = self.rule_engine.zones
            if self._rule_zone_id != zone_id or not cached_zones or cached_zones[0].get("polygon") is not zone.polygon:
                self.rule_engine.zones = [{"id": zone_id, "polygon": zone.polygon}]
                self._rule_zone_id = zone_id
            for trk in tracks:
                for rule_event in self.rule_engine.check_zones(trk.track_id, trk.footpoint, now_ts):
                    event = {
                        "camera_id": camera_id,
                        "stream_epoch": stream_epoch,
                        "event_type": "suspicious_loitering",
                        "zone_id": zone_id,
                        "track_id": trk.track_id,
                        "bbox_norm": trk.bbox_norm,
                        "confidence": trk.confidence,
                        "explanation": self.rule_engine.explain(rule_event),
                        "model_id": model_id,
                    }
                    transactional_write(event, dedup_key=f"{camera_id}:loiter:{zone_id}:{trk.track_id}:{stream_epoch}:{int(now_ts // 10)}")
                    self.events_created += 1
                    if primary_event is None:
                        primary_event = event

        # 1. Restricted Zone / Tripwire Intrusion (with hysteresis and debounce cooldown)
        intrusion_classes = {"person", "car", "truck", "bus", "motorcycle"}
        for trk in tracks:
            if trk.class_name not in intrusion_classes:
                continue
            is_line = is_line_zone
            intruding = is_intrusion(trk.footpoint, zone, track=trk)
            if is_line:
                if intruding:
                    self._active_line_intruders.add(trk.track_id)
                    self._line_miss_count[trk.track_id] = 0
                elif trk.track_id in self._active_line_intruders:
                    # Hysteresis latch: expire after N consecutive non-intrusions
                    # so the exit-count path stays reachable.
                    misses = self._line_miss_count.get(trk.track_id, 0) + 1
                    self._line_miss_count[trk.track_id] = misses
                    if misses < 5:
                        intruding = True
                    else:
                        self._active_line_intruders.discard(trk.track_id)
                        self._line_miss_count.pop(trk.track_id, None)

            if intruding:
                intrusion_track_ids.add(trk.track_id)
                self._track_outside_count[trk.track_id] = 0
                last_alert = self._last_intrusion_alert_time.get((zone_id, trk.track_id), 0.0)
                # Debounce: alert once per continuous presence, or after at least 4s cooldown
                if trk.track_id not in self.alerted_tracks and (now_ts - last_alert) >= 4.0:
                    self.alerted_tracks.add(trk.track_id)
                    self._last_intrusion_alert_time[(zone_id, trk.track_id)] = now_ts
                    dedup = f"{camera_id}:{zone_id}:{trk.track_id}:{stream_epoch}:{int(now_ts // 10)}"
                    rule_name = "tripwire_line_crossing" if is_line else "restricted_zone_intrusion"
                    observed_desc = f"track {trk.track_id} crossed perimeter line" if is_line else f"track {trk.track_id} footpoint inside polygon"
                    threshold_desc = "perimeter line crossed" if is_line else "inside restricted zone"
                    event = {
                        "camera_id": camera_id,
                        "stream_epoch": stream_epoch,
                        "event_type": "zone_intrusion",
                        "zone_id": zone_id,
                        "track_id": trk.track_id,
                        "bbox_norm": trk.bbox_norm,
                        "confidence": trk.confidence,
                        "explanation": {
                            "rule": rule_name,
                            "zone": zone_name,
                            "observed": observed_desc,
                            "threshold": threshold_desc,
                        },
                        "model_id": model_id,
                    }
                    transactional_write(event, dedup_key=dedup)
                    self.events_created += 1
                    if primary_event is None:
                        primary_event = event
            else:
                # Track is outside zone - if previously alerted for intrusion, track sustained exit
                if trk.track_id in self.alerted_tracks:
                    count = self._track_outside_count.get(trk.track_id, 0) + 1
                    self._track_outside_count[trk.track_id] = count
                    if count >= 15:
                        self.alerted_tracks.discard(trk.track_id)
                        self._active_line_intruders.discard(trk.track_id)
                        self._line_miss_count.pop(trk.track_id, None)
                        last_exit = self._last_exit_alert_time.get((zone_id, trk.track_id), 0.0)
                        if (now_ts - last_exit) >= 3.0:
                            self._last_exit_alert_time[(zone_id, trk.track_id)] = now_ts
                            dedup = f"{camera_id}:{zone_id}:exit:{trk.track_id}:{stream_epoch}:{int(now_ts // 10)}"
                            is_line = is_line_zone
                            rule_name = "tripwire_line_exit" if is_line else "restricted_zone_exit"
                            observed_desc = f"track {trk.track_id} exited line perimeter" if is_line else f"track {trk.track_id} exited restricted zone"
                            threshold_desc = "outside line perimeter" if is_line else "outside restricted zone"
                            ev_exit = {
                                "camera_id": camera_id,
                                "stream_epoch": stream_epoch,
                                "event_type": "zone_exit",
                                "zone_id": zone_id,
                                "track_id": trk.track_id,
                                "bbox_norm": trk.bbox_norm,
                                "confidence": trk.confidence,
                                "explanation": {
                                    "rule": rule_name,
                                    "zone": zone_name,
                                    "observed": observed_desc,
                                    "threshold": threshold_desc,
                                },
                                "model_id": model_id,
                            }
                            transactional_write(ev_exit, dedup_key=dedup)
                            self.events_created += 1
                            if primary_event is None:
                                primary_event = ev_exit
                else:
                    self._track_outside_count[trk.track_id] = 0

        # Presence continuity requires visibility: an alerted track unseen for
        # more than 3 sampled frames (the tracker's visible-hide threshold)
        # ends its presence HERE with its last-known position - a returnee
        # re-alerts instead of staying muted on a stale presence.
        visible_ids = {t.track_id for t in tracks}
        for tid in list(self.alerted_tracks):
            if tid in visible_ids:
                self._unseen_streak.pop(tid, None)
                continue
            if self._unseen_streak.get(tid, 0) < 3:
                self._unseen_streak[tid] = self._unseen_streak.get(tid, 0) + 1
                continue
            self.alerted_tracks.discard(tid)
            self._track_outside_count.pop(tid, None)
            self._active_line_intruders.discard(tid)
            self._line_miss_count.pop(tid, None)
            self._unseen_streak.pop(tid, None)
            internal = self.tracker.tracks.get(tid)
            if internal is None:
                continue
            ev_end = self._end_presence_event(
                track_id=tid,
                bbox_norm=internal.bbox_norm,
                confidence=internal.confidence,
                camera_id=camera_id,
                stream_epoch=stream_epoch,
                zone=zone,
                zone_id=zone_id,
                zone_name=zone_name,
                is_line_zone=is_line_zone,
                model_id=model_id,
                now_ts=now_ts,
            )
            if ev_end is None:
                continue
            transactional_write(ev_end, dedup_key=f"{camera_id}:{zone_id}:exit:{tid}:{stream_epoch}:{int(now_ts // 10)}")
            self.events_created += 1
            if primary_event is None:
                primary_event = ev_end

        # 2. Target entered FOV (only for tracks with confidence >= 0.48 not already reported as zone intrusions)
        for entry in new_entries:
            if entry.class_name in intrusion_classes and entry.track_id not in intrusion_track_ids and entry.confidence >= 0.48:
                dedup = f"{camera_id}:entered:{entry.track_id}:{stream_epoch}"
                ev_enter = {
                    "camera_id": camera_id,
                    "stream_epoch": stream_epoch,
                    "event_type": "target_entered",
                    "zone_id": zone_id,
                    "track_id": entry.track_id,
                    "bbox_norm": entry.bbox_norm,
                    "confidence": entry.confidence,
                    "explanation": {
                        "rule": "target_entered_fov",
                        "zone": zone_name,
                        "observed": f"{entry.class_name} #{entry.track_id} entered camera field of view",
                        "threshold": "fov_entry",
                    },
                    "model_id": model_id,
                }
                transactional_write(ev_enter, dedup_key=dedup)
                self.events_created += 1
        # 3. Watchlist Suspect Identified (tactical alert when track is locked to a suspect or critical target identified)
        for trk in tracks:
            _ident = trk.identity
            _tier = _ident.get("tier") if _ident else None
            is_critical = bool(_ident and _ident.get("threat_level") == "CRITICAL")
            is_locked = bool(getattr(trk, "identity_locked", False))
            # Critical alerts require RED tier or a confirmed lock; AMBER+CRITICAL
            # tentative matches must not fire.
            should_alert = (is_locked or (is_critical and _tier == "RED")) and _ident
            if should_alert and trk.track_id not in self.watchlist_alerted_tracks:
                self.watchlist_alerted_tracks.add(trk.track_id)
                ident = trk.identity
                dedup = f"{camera_id}:watchlist:{ident['entry_id']}:{trk.track_id}:{stream_epoch}"
                ev_watchlist = {
                    "camera_id": camera_id,
                    "stream_epoch": stream_epoch,
                    "event_type": "watchlist_suspect_identified",
                    "zone_id": zone_id,
                    "track_id": trk.track_id,
                    "bbox_norm": trk.bbox_norm,
                    "confidence": ident["score"],
                    "explanation": {
                        "rule": "watchlist_biometric_match",
                        "suspect_id": ident["entry_id"],
                        "suspect_name": ident["name"],
                        "threat_level": ident.get("threat_level", ident.get("tier", "RED")),
                        "score": round(ident["score"], 3),
                        "tier": ident.get("tier", "RED"),
                    },
                    "model_id": getattr(self, "model_id", "sface"),
                }
                transactional_write(ev_watchlist, dedup_key=dedup)
                self.events_created += 1
                if primary_event is None:
                    primary_event = ev_watchlist

        # 4. Target exited FOV / Zone Exit on Termination
        for term in terminated:
            was_zone_alerted = term.track_id in self.alerted_tracks
            self.alerted_tracks.discard(term.track_id)
            self.watchlist_alerted_tracks.discard(term.track_id)
            self._active_line_intruders.discard(term.track_id)
            self._track_outside_count.pop(term.track_id, None)
            self._unseen_streak.pop(term.track_id, None)
            self._line_miss_count.pop(term.track_id, None)

            # Safety net (visibility expiry above normally reports first):
            # last-known position decides exit vs lost.
            if was_zone_alerted:
                ev_end = self._end_presence_event(
                    track_id=term.track_id,
                    bbox_norm=term.bbox_norm,
                    confidence=term.confidence,
                    camera_id=camera_id,
                    stream_epoch=stream_epoch,
                    zone=zone,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    is_line_zone=is_line_zone,
                    model_id=model_id,
                    now_ts=now_ts,
                )
                if ev_end is not None:
                    transactional_write(ev_end, dedup_key=f"{camera_id}:{zone_id}:exit:{term.track_id}:{stream_epoch}:{int(now_ts // 10)}")
                    self.events_created += 1
                    if primary_event is None:
                        primary_event = ev_end

            # FOV exit for confirmed tracks
            last_fov_exit = self._last_exit_alert_time.get((-1, term.track_id), 0.0)
            if term.hits >= 3 and term.confidence >= 0.45 and (now_ts - last_fov_exit) >= 3.0:
                self._last_exit_alert_time[(-1, term.track_id)] = now_ts
                dedup = f"{camera_id}:exited:{term.track_id}:{stream_epoch}"
                ev_exit = {
                    "camera_id": camera_id,
                    "stream_epoch": stream_epoch,
                    "event_type": "target_exited",
                    "zone_id": zone_id,
                    "track_id": term.track_id,
                    "bbox_norm": term.bbox_norm,
                    "confidence": term.confidence,
                    "explanation": {
                        "rule": "target_exited_fov",
                        "zone": zone_name,
                        "observed": f"{term.class_name} #{term.track_id} exited camera field of view",
                        "threshold": "fov_exit",
                    },
                    "model_id": model_id,
                }
                transactional_write(ev_exit, dedup_key=dedup)
                self.events_created += 1
                if primary_event is None:
                    primary_event = ev_exit

        self.frame_idx += 1
        return primary_event

    def process_video_file(
        self,
        path: str,
        max_frames: int = 30,
        sample_stride: int | None = None,
        enable_face: bool | None = None,
        face_stride: int | None = None,
    ) -> list[dict]:
        """Process a real video file via PyAV (preferred) or OpenCV fallback - for Phase 3 gate.

        Optimisations applied:
        - PyAV demux/decode with time_base provenance (ADR-0002) instead of sole VideoCapture
        - sample_stride: analyse every Nth decoded frame (default instance sample_stride, e.g. 3 => 10 FPS from 30 FPS source)
          Saves YOLO ~13ms + tracking per skipped frame. For uploads 5 FPS cadence recommended (stride 6).
        - face_stride: run YuNet only every M analysed frames (default 3 => face 3.3 FPS when sample_stride=3)
          Saves ~8ms per non-face frame. Total uploaded pipeline ~22ms -> ~8ms on skipped-face frames.
        - max_face_size downscale keeps YuNet bounded (docs/benchmarks 7.88ms @640x480).
        - bounded queues still enforced so memory-bound under flood.

        Returns list of events; side-effects: self.last_detections / last_tracks / last_faces are set to last analysed frame.
        """
        # Allow per-call override without mutating permanently? We mutate for simplicity but restore after.
        orig_sample_stride = self.sample_stride
        orig_face_stride = self.face_stride
        orig_enable_face = self.enable_face
        if sample_stride is not None:
            self.sample_stride = max(1, sample_stride)
        if face_stride is not None:
            self.face_stride = max(1, face_stride)
        if enable_face is not None:
            self.enable_face = enable_face

        events: list[dict] = []
        decoded = 0
        analysed = 0
        # Prefer PyAV for correct PTS/time_base and bounded queue semantics
        use_av = False
        try:
            import av  # type: ignore

            use_av = True
        except Exception:
            use_av = False

        try:
            if use_av:
                try:
                    container = av.open(path)
                except Exception:
                    # Fallback to cv2 if PyAV cannot open (e.g. codec issue)
                    use_av = False
                else:
                    stream = next((s for s in container.streams if s.type == "video"), None)
                    if stream is None:
                        container.close()
                        use_av = False
                    else:
                        for frame in container.decode(stream):
                            if analysed >= max_frames:
                                break
                            decoded += 1
                            try:
                                arr = frame.to_ndarray(format="bgr24")
                            except Exception:
                                continue
                            before_idx = self.frame_idx
                            ev = self.process_frame(arr)
                            # Only count frames where detector actually ran (not sampled-skipped)
                            was_skipped = (before_idx % self.sample_stride != 0) if self.sample_stride > 1 else False
                            if was_skipped:
                                continue
                            analysed += 1
                            if ev:
                                events.append(ev)
                            if decoded >= max_frames * self.sample_stride + 20 and analysed >= max_frames:
                                break
                        container.close()
                        self.sample_stride = orig_sample_stride
                        self.face_stride = orig_face_stride
                        self.enable_face = orig_enable_face
                        return events
            if not use_av:
                cap = cv2.VideoCapture(path)
                n = 0
                decoded = 0
                while cap.isOpened() and n < max_frames:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    decoded += 1
                    ev = self.process_frame(frame)
                    # process_frame increments frame_idx internally; we count analysed only when not skipped
                    # If sample_stride>1, some frames are early-returned and n should not advance? We advance n only for analysed frames.
                    # Use frame_idx stride to decide: only count if detector ran
                    if self.sample_stride == 1 or ((self.frame_idx - 1) % self.sample_stride == 0):
                        n += 1
                        if ev:
                            events.append(ev)
                    else:
                        # Skipped frame not counted toward max_frames (max_frames = analysed frames)
                        continue
                cap.release()
        finally:
            self.sample_stride = orig_sample_stride
            self.face_stride = orig_face_stride
            self.enable_face = orig_enable_face
        return events

    def get_last_observations(self) -> dict:
        """Helper for API layer: returns last frame observations including faces."""
        return {
            "detections": self.last_detections,
            "tracks": [
                {
                    "track_id": t.track_id,
                    "class_name": t.class_name,
                    "confidence": t.confidence,
                    "bbox_norm": t.bbox_norm,
                    "identity": getattr(t, "identity", None),
                    "identity_locked": getattr(t, "identity_locked", False),
                }
                for t in self.last_tracks
            ],
            "faces": self.last_faces,
            "frame_at": time.time(),
            "runtime": getattr(self.detector, "runtime", "mock"),
        }
