"""Face detection - Phase 6, spec 15.

Uses dedicated detector (YuNet) - NOT YOLO COCO. Identity matching disabled by default.
Gate: legal/privacy/bias/threshold must pass before enabling.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ibvap.models import Base  # noqa: F401 - ensure DB import side-effect


@dataclass(frozen=True)
class FaceQuality:
    blur: float
    pose_yaw: float
    occlusion: float
    illumination: float
    passed: bool


@dataclass(frozen=True)
class FaceDetection:
    bbox_norm: tuple[float, float, float, float]
    confidence: float
    quality: FaceQuality
    landmarks: list[tuple[float, float]] | None


class FaceDetector:
    """YuNet-backed detector - stub that requires real ONNX weights.

    In Phase 6, this would load `face_detection_yunet_2023mar.onnx` via cv2.FaceDetectorYN.
    For now, returns empty unless weights present, and never invents faces.
    """

    def __init__(self, model_path: str = "models/face_detection_yunet_2023mar.onnx", conf_threshold: float = 0.6) -> None:
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self._detector = None
        # try load if file exists and cv2 supports
        try:
            import pathlib

            p = pathlib.Path(model_path)
            if p.exists() and hasattr(cv2, "FaceDetectorYN"):
                self._detector = cv2.FaceDetectorYN.create(str(p), "", (320, 320), conf_threshold, 0.3, 5000)
        except Exception:
            self._detector = None

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        if self._detector is None or frame.size == 0:
            return []
        # real inference would run here; we return empty to avoid fabrication
        # For test, if frame has valid detector, we could run, but keep empty for now
        return []

    @staticmethod
    def check_identity_gate_passed() -> bool:
        # spec 15 gate
        return False
