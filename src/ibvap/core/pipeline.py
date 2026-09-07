"""Minimal pipeline for Phase 3 slice - synthetic video -> mock detector -> tracker -> zone -> outbox.

Spec 6: Bounded queues + sampling. This slice proves one video creates one persisted event.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from ibvap.core.detector import DetectorProvider, MockPersonDetector, ONNXDetectorProvider
from ibvap.core.queue import BoundedQueue
from ibvap.core.tracker import CentroidTracker
from ibvap.core.zone_engine import DEFAULT_ZONE, is_intrusion
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
        max_face_size: int = 1280,
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
        # bounded queues per spec 10
        self.q_demux_to_sample = BoundedQueue("demux->sample", max_size=2, max_age_ms=400)
        self.q_sample_to_infer = BoundedQueue("sample->infer", max_size=2, max_age_ms=400)
        self.frame_idx = 0
        self.events_created = 0
        self.alerted_tracks: set[int] = set()
        self.watchlist_alerted_tracks: set[int] = set()
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

    def process_frame(self, frame: np.ndarray) -> dict | None:
        """Process one frame; return event dict if intrusion detected else None.

        Optimisation:
        - bounded queues drop stale frames (spec 10 overload -> drop old, not grow latency)
        - sample_stride: run heavy detector only every Nth frame (uploaded video 5 FPS cadence = stride 6 for 30 FPS source)
        - face_stride: run YuNet only every M sampled frames (e.g. 3 => face every 3rd analysis frame)
        - large-frame downscale for face (max_face_size) to keep YuNet <10ms
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

        # detect (person/vehicle)
        if self.detector_handle is not None and hasattr(self.detector_handle, "acquire"):
            with self.detector_handle.acquire() as det:
                detections = det.detect(frame, self.frame_idx)
                self.model_id = getattr(det, "model_id", "yolo26n")
                self.runtime = getattr(det, "runtime", "directml")
        else:
            detections = self.detector.detect(frame, self.frame_idx)
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
        tracks, new_entries, terminated = self.tracker.update(det_dicts, timestamp=time.time())
        self.last_tracks = tracks

        # ---- face detection (optimized, sampled) ----
        # Retain previous faces across stride-skipped frames to avoid flicker; only update on sampled face frames
        new_faces_detected = False
        if not hasattr(self, "last_faces"):
            self.last_faces = []
        if self.enable_face and self.face_detector is not None:
            # Run YuNet only every face_stride sampled frames to save ~8ms per frame
            sampled_idx = self.frame_idx // self.sample_stride if self.sample_stride > 1 else self.frame_idx
            if (sampled_idx % self.face_stride) == 0:
                try:
                    # Downscale huge frames for face (normalized bbox is resolution-invariant, so no remap needed)
                    fd_frame = frame
                    h, w = frame.shape[:2]
                    if max(h, w) > self.max_face_size:
                        scale = self.max_face_size / float(max(h, w))
                        nw, nh = int(w * scale), int(h * scale)
                        if nw > 0 and nh > 0:
                            fd_frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
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
                        if f.quality.passed
                    ]
                    self.faces_analyzed += 1
                    new_faces_detected = bool(self.last_faces)
                except Exception:
                    pass

        # ---- Hungarian Head-ROI track-to-face spatial fusion & biometric identification ----
        if new_faces_detected and self.last_faces and self.face_recognizer is not None:
            try:
                from ibvap.core.association import associate_faces_to_tracks
                from ibvap.core.watchlist import get_watchlist_store

                assignments = associate_faces_to_tracks(tracks, self.last_faces)
                wl_store = get_watchlist_store()
                crop_frame = getattr(self, "_last_face_frame", frame)
                for trk_id, face_info in assignments.items():
                    target_track = next((t for t in tracks if t.track_id == trk_id), None)
                    if target_track is None:
                        continue
                    raw_f = face_info.get("_raw")
                    if raw_f is not None and getattr(getattr(raw_f, "quality", None), "passed", True):
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
                            if confirmed:
                                wl_store.record_sighting(match.entry_id, time.time())
            except Exception:
                pass

        primary_event: dict | None = None
        intrusion_track_ids: set[int] = set()

        # 1. Restricted Zone Intrusion (alert once per continuous presence in zone)
        for trk in tracks:
            if trk.class_name not in {"person", "car", "truck", "bus", "motorcycle"}:
                continue
            if is_intrusion(trk.footpoint, self.zone):
                intrusion_track_ids.add(trk.track_id)
                if trk.track_id not in self.alerted_tracks:
                    self.alerted_tracks.add(trk.track_id)
                    dedup = f"{self.camera_id}:{self.zone.id}:{trk.track_id}:{self.stream_epoch}"
                    event = {
                        "camera_id": self.camera_id,
                        "stream_epoch": self.stream_epoch,
                        "event_type": "zone_intrusion",
                        "zone_id": self.zone.id,
                        "track_id": trk.track_id,
                        "bbox_norm": trk.bbox_norm,
                        "confidence": trk.confidence,
                        "explanation": {
                            "rule": "restricted_zone_intrusion",
                            "zone": self.zone.name,
                            "observed": f"track {trk.track_id} footpoint {trk.footpoint} inside polygon",
                            "threshold": "inside restricted zone",
                        },
                        "model_id": self.detector.model_id,
                    }
                    transactional_write(event, dedup_key=dedup)
                    self.events_created += 1
                    if primary_event is None:
                        primary_event = event
            else:
                self.alerted_tracks.discard(trk.track_id)

        # 2. Target entered FOV (only for tracks with confidence >= 0.48 not already reported as zone intrusions)
        for entry in new_entries:
            if entry.class_name in {"person", "car", "truck", "bus", "motorcycle"} and entry.track_id not in intrusion_track_ids and entry.confidence >= 0.48:
                dedup = f"{self.camera_id}:entered:{entry.track_id}:{self.stream_epoch}"
                ev_enter = {
                    "camera_id": self.camera_id,
                    "stream_epoch": self.stream_epoch,
                    "event_type": "target_entered",
                    "zone_id": self.zone.id,
                    "track_id": entry.track_id,
                    "bbox_norm": entry.bbox_norm,
                    "confidence": entry.confidence,
                    "explanation": {
                        "rule": "target_entered_fov",
                        "zone": self.zone.name,
                        "observed": f"{entry.class_name} #{entry.track_id} entered camera field of view",
                        "threshold": "fov_entry",
                    },
                    "model_id": self.detector.model_id,
                }
                transactional_write(ev_enter, dedup_key=dedup)
                self.events_created += 1
        # 3. Watchlist Suspect Identified (tactical alert when track is locked to a suspect or critical target identified)
        for trk in tracks:
            is_critical = trk.identity and trk.identity.get("threat_level") == "CRITICAL"
            should_alert = (getattr(trk, "identity_locked", False) or is_critical) and trk.identity
            if should_alert and trk.track_id not in self.watchlist_alerted_tracks:
                self.watchlist_alerted_tracks.add(trk.track_id)
                ident = trk.identity
                dedup = f"{self.camera_id}:watchlist:{ident['entry_id']}:{trk.track_id}:{self.stream_epoch}"
                ev_watchlist = {
                    "camera_id": self.camera_id,
                    "stream_epoch": self.stream_epoch,
                    "event_type": "watchlist_suspect_identified",
                    "zone_id": self.zone.id,
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

        # 4. Target exited FOV (only for tracks that were confirmed with >= 2 hits)
        for term in terminated:
            self.alerted_tracks.discard(term.track_id)
            self.watchlist_alerted_tracks.discard(term.track_id)
            if term.hits >= 2 and term.confidence >= 0.45:
                dedup = f"{self.camera_id}:exited:{term.track_id}:{self.stream_epoch}"
                ev_exit = {
                    "camera_id": self.camera_id,
                    "stream_epoch": self.stream_epoch,
                    "event_type": "target_exited",
                    "zone_id": self.zone.id,
                    "track_id": term.track_id,
                    "bbox_norm": term.bbox_norm,
                    "confidence": term.confidence,
                    "explanation": {
                        "rule": "target_exited_fov",
                        "zone": self.zone.name,
                        "observed": f"{term.class_name} #{term.track_id} exited camera field of view",
                        "threshold": "fov_exit",
                    },
                    "model_id": self.detector.model_id,
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
