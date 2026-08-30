"""Face detection and biometric identity recognition - Phase 6, spec 15.

Uses dedicated detector (YuNet) and recognizer (SFace) from OpenCV Zoo.
Identity matching is disabled by default behind an authorization/privacy gate.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from ibvap.models import Base  # noqa: F401 - ensure DB import side-effect

if TYPE_CHECKING:
    from ibvap.config import AppConfig, Settings


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
    raw_row: np.ndarray | None = None


def check_identity_gate_passed(settings: Settings | AppConfig | Any | None = None) -> bool:
    """Verify whether face identity recognition is legally and administratively authorized."""
    if settings is not None:
        if hasattr(settings, "enable_face_identity") and settings.enable_face_identity:
            return True
        if hasattr(settings, "app") and getattr(settings.app, "enable_face_identity", False):
            return True

    for env_key in ("IBVAP_ENABLE_FACE_IDENTITY", "IBVAP_APP__ENABLE_FACE_IDENTITY"):
        val = os.getenv(env_key, "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True

    return False


class FaceDetector:
    """YuNet-backed face detector (OpenCV Zoo).

    Performs dynamic input sizing, bounding box normalization, 5-point landmark extraction,
    and image quality scoring (blur, illumination, pose estimation).
    """

    def __init__(
        self,
        model_path: str = "models/face_detection_yunet_2023mar.onnx",
        conf_threshold: float = 0.6,
    ) -> None:
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self._detector: cv2.FaceDetectorYN | None = None

        p = pathlib.Path(model_path)
        if p.exists() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self._detector = cv2.FaceDetectorYN.create(
                    str(p),
                    "",
                    (320, 320),
                    score_threshold=conf_threshold,
                    nms_threshold=0.3,
                    top_k=5000,
                )
            except Exception:
                self._detector = None

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        """Detect faces in frame and return normalized bounding boxes and quality metrics."""
        if self._detector is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        if h <= 0 or w <= 0:
            return []

        try:
            self._detector.setInputSize((w, h))
            _, faces = self._detector.detect(frame)
        except Exception:
            return []

        if faces is None or len(faces) == 0:  # pyright: ignore[reportUnnecessaryComparison]
            return []

        results: list[FaceDetection] = []
        for face in faces:
            x, y, fw, fh = float(face[0]), float(face[1]), float(face[2]), float(face[3])
            conf = float(face[14])

            # Normalized bounding box [0, 1] clamped
            x1 = max(0.0, x) / w
            y1 = max(0.0, y) / h
            x2 = min(float(w), x + fw) / w
            y2 = min(float(h), y + fh) / h
            bbox_norm = (float(x1), float(y1), float(x2), float(y2))

            # 5 facial landmarks: right eye, left eye, nose tip, right mouth corner, left mouth corner
            landmarks: list[tuple[float, float]] = [(float(face[4 + 2 * j]), float(face[5 + 2 * j])) for j in range(5)]

            # Quality metrics: crop ROI
            px1 = max(0, int(round(x)))
            py1 = max(0, int(round(y)))
            px2 = min(w, int(round(x + fw)))
            py2 = min(h, int(round(y + fh)))

            if px2 > px1 and py2 > py1:
                crop = frame[py1:py2, px1:px2]
                gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
                blur = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
                illumination = float(np.mean(gray_crop))
            else:
                blur = 0.0
                illumination = 0.0

            # Pose yaw estimation from eye distance and nose horizontal displacement
            right_eye_x = landmarks[0][0]
            left_eye_x = landmarks[1][0]
            nose_x = landmarks[2][0]
            eye_dist = abs(left_eye_x - right_eye_x)
            eye_mid = (right_eye_x + left_eye_x) / 2.0
            pose_yaw = float((nose_x - eye_mid) / (eye_dist + 1e-6) * 90.0) if eye_dist > 0 else 0.0
            occlusion = 0.0

            quality_passed = bool(blur >= 10.0 and illumination >= 20.0 and conf >= self.conf_threshold)

            quality = FaceQuality(
                blur=blur,
                pose_yaw=pose_yaw,
                occlusion=occlusion,
                illumination=illumination,
                passed=quality_passed,
            )

            results.append(
                FaceDetection(
                    bbox_norm=bbox_norm,
                    confidence=conf,
                    quality=quality,
                    landmarks=landmarks,
                    raw_row=np.asarray(face, dtype=np.float32).copy(),
                )
            )

        return results

    @staticmethod
    def check_identity_gate_passed(settings: Settings | AppConfig | Any | None = None) -> bool:
        """Convenience method checking identity recognition authorization."""
        return check_identity_gate_passed(settings)


class FaceRecognizer:
    """SFace-backed feature extractor and biometric matcher (OpenCV Zoo).

    Generates 128-dimensional L2-normalized embeddings and calculates cosine similarity
    against enrolled watchlist features.
    """

    def __init__(self, model_path: str = "models/face_recognition_sface_2021dec.onnx") -> None:
        self.model_path = model_path
        self._recognizer: cv2.FaceRecognizerSF | None = None

        p = pathlib.Path(model_path)
        if p.exists() and hasattr(cv2, "FaceRecognizerSF"):
            try:
                self._recognizer = cv2.FaceRecognizerSF.create(str(p), "")
            except Exception:
                self._recognizer = None

    def align_crop(self, frame: np.ndarray, face_row: np.ndarray | FaceDetection) -> np.ndarray:
        """Align and crop face ROI to 112x112 standard representation."""
        if self._recognizer is None or frame.size == 0:
            return np.zeros((112, 112, 3), dtype=np.uint8)

        if isinstance(face_row, FaceDetection):
            if face_row.raw_row is not None:
                row_arr = face_row.raw_row
            else:
                return np.zeros((112, 112, 3), dtype=np.uint8)
        else:
            row_arr = np.asarray(face_row, dtype=np.float32)

        try:
            aligned = self._recognizer.alignCrop(frame, row_arr)
            return aligned
        except Exception:
            return np.zeros((112, 112, 3), dtype=np.uint8)

    def extract_feature(self, aligned_crop: np.ndarray) -> np.ndarray:
        """Extract 128-dimensional embedding from aligned 112x112 crop."""
        if self._recognizer is None or aligned_crop.size == 0:
            return np.zeros((1, 128), dtype=np.float32)

        if aligned_crop.shape[:2] != (112, 112):
            aligned_crop = cv2.resize(aligned_crop, (112, 112))

        try:
            feat = self._recognizer.feature(aligned_crop)
            return np.asarray(feat, dtype=np.float32)
        except Exception:
            return np.zeros((1, 128), dtype=np.float32)

    def match(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """Compute cosine similarity score between two 128-d feature vectors."""
        if self._recognizer is None or feat1.size == 0 or feat2.size == 0:
            return 0.0

        try:
            score = float(
                self._recognizer.match(
                    np.asarray(feat1, dtype=np.float32),
                    np.asarray(feat2, dtype=np.float32),
                    cv2.FaceRecognizerSF_FR_COSINE,
                )
            )
            return score
        except Exception:
            return 0.0

    def identify(
        self,
        feature: np.ndarray,
        watchlist: dict[str, np.ndarray],
        threshold: float = 0.363,
    ) -> tuple[str | None, float]:
        """Match feature against enrolled watchlist and return (best_identity, score)."""
        if not watchlist or self._recognizer is None or feature.size == 0:
            return None, 0.0

        best_id: str | None = None
        best_score: float = -1.0

        for identity, enrolled_feat in watchlist.items():
            sim = self.match(feature, enrolled_feat)
            if sim > best_score:
                best_score = sim
                best_id = identity

        if best_score >= threshold and best_id is not None:
            return best_id, best_score

        return None, max(0.0, best_score)

    # Alias for convenience / interface compatibility
    match_identity = identify
