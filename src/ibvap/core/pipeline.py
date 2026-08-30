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


class MiniPipeline:
    """Camera-scoped pipeline - proves E2E slice with ONNX detector or mock detector."""

    def __init__(
        self,
        camera_id: str,
        stream_epoch: int = 0,
        detector: DetectorProvider | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.stream_epoch = stream_epoch
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

    def process_frame(self, frame: np.ndarray) -> dict | None:
        """Process one frame; return event dict if intrusion detected else None."""
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

        # detect
        detections = self.detector.detect(frame, self.frame_idx)
        det_dicts = [
            {
                "bbox_norm": d.bbox_norm,
                "class_name": d.class_name,
                "class_id": d.class_id,
                "confidence": d.confidence,
            }
            for d in detections
        ]
        tracks, new_entries, _ = self.tracker.update(det_dicts, timestamp=time.time())

        # zone check - bottom-center footpoint
        for trk in tracks:
            if trk.class_name not in {"person", "car", "truck", "bus", "motorcycle"}:
                continue
            if is_intrusion(trk.footpoint, self.zone):
                # dedup key: camera:zone:track:window (cooldown 5s)
                dedup = f"{self.camera_id}:{self.zone.id}:{trk.track_id}:{int(time.time() // 5)}"
                # check if already created this window
                # we rely on transactional_write idempotency
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
                self.frame_idx += 1
                return event

        self.frame_idx += 1
        return None

    def process_video_file(self, path: str, max_frames: int = 30) -> list[dict]:
        """Process a real video file via PyAV/OpenCV - for Phase 3 gate."""
        cap = cv2.VideoCapture(path)
        events: list[dict] = []
        n = 0
        while cap.isOpened() and n < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            ev = self.process_frame(frame)
            if ev:
                events.append(ev)
            n += 1
        cap.release()
        return events
