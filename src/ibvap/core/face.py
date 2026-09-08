"""Face detection and biometric identity recognition - Phase 6, spec 15.

Uses dedicated detector (YuNet) and recognizer (SFace) from OpenCV Zoo.
Identity matching is disabled by default behind an authorization/privacy gate.
"""

from __future__ import annotations

import math
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
    geometry_valid: bool = True


@dataclass(frozen=True)
class FaceDetection:
    bbox_norm: tuple[float, float, float, float]
    confidence: float
    quality: FaceQuality
    landmarks: list[tuple[float, float]] | None
    raw_row: np.ndarray | None = None


def _pt_line_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Perpendicular distance from point (px, py) to line segment (ax, ay)-(bx, by)."""
    line_len = math.hypot(bx - ax, by - ay)
    if line_len < 1e-6:
        return math.hypot(px - ax, py - ay)
    return abs((by - ay) * px - (bx - ax) * py + bx * ay - by * ax) / line_len


class FaceQualityAssessment:
    """Rigorous face quality and landmark geometry assessment engine."""

    @staticmethod
    def validate_geometry(
        fw: float,
        fh: float,
        landmarks: list[tuple[float, float]] | None,
        min_size: float = 24.0,
    ) -> bool:
        """Validate 5-point facial landmarks for plausible human facial geometry.

        OpenCV Zoo YuNet landmark ordering:
          0: right eye (re)
          1: left eye (le)
          2: nose tip (nt)
          3: right mouth corner (rm)
          4: left mouth corner (lm)
        """
        if fw < min_size or fh < min_size:
            return False

        aspect_ratio = fw / max(1e-5, fh)
        if aspect_ratio < 0.42 or aspect_ratio > 1.60:
            return False

        if not landmarks or len(landmarks) != 5:
            return False

        re_x, re_y = landmarks[0]
        le_x, le_y = landmarks[1]
        nt_x, nt_y = landmarks[2]
        rm_x, rm_y = landmarks[3]
        lm_x, lm_y = landmarks[4]

        # 1. Landmark ordering & non-inversion check
        if re_x >= le_x or rm_x >= lm_x:
            return False

        # 2. Inter-ocular distance & mouth width
        eye_dist = math.hypot(le_x - re_x, le_y - re_y)
        if eye_dist < 6.0:
            return False
        ratio_eyes = eye_dist / fw
        if ratio_eyes < 0.16 or ratio_eyes > 0.82:
            return False

        mouth_dist = math.hypot(lm_x - rm_x, lm_y - rm_y)
        if mouth_dist < 4.0:
            return False
        ratio_mouth = mouth_dist / fw
        if ratio_mouth < 0.10 or ratio_mouth > 0.85:
            return False

        # 3. Eye tilt (roll angle check)
        eye_tilt = abs(le_y - re_y) / eye_dist
        if eye_tilt > 0.70:
            return False

        # 4. Vertical anatomy ordering
        eye_mid_y = (re_y + le_y) / 2.0
        mouth_mid_y = (rm_y + lm_y) / 2.0
        v_dist = mouth_mid_y - eye_mid_y
        if v_dist < 6.0:
            return False

        # Nose tip must be vertically between eye line and mouth line
        if nt_y < eye_mid_y - 0.05 * fh or nt_y > mouth_mid_y + 0.05 * fh:
            return False

        nose_v_ratio = (nt_y - eye_mid_y) / max(1e-5, v_dist)
        if nose_v_ratio < 0.12 or nose_v_ratio > 0.88:
            return False

        # 5. Eye-Nose-Mouth vertical aspect ratio
        enm_aspect = v_dist / max(1e-5, eye_dist)
        if enm_aspect < 0.35 or enm_aspect > 2.40:
            return False

        # 6. Non-degenerate triangular area (Gauss shoelace formula)
        # Area of eye-nose triangle (re, le, nt)
        area_eye_nose = 0.5 * abs(re_x * (le_y - nt_y) + le_x * (nt_y - re_y) + nt_x * (re_y - le_y))
        norm_area_en = area_eye_nose / (fw * fh)
        if norm_area_en < 0.010:
            return False

        # Area of nose-mouth triangle (nt, rm, lm)
        area_nose_mouth = 0.5 * abs(nt_x * (rm_y - lm_y) + rm_x * (lm_y - nt_y) + lm_x * (nt_y - rm_y))
        norm_area_nm = area_nose_mouth / (fw * fh)
        if norm_area_nm < 0.008:
            return False

        # 7. Collinearity check: lateral landmarks on near-frontal faces
        if eye_tilt < 0.15:
            d_r = _pt_line_distance(nt_x, nt_y, re_x, re_y, rm_x, rm_y) / fw
            d_l = _pt_line_distance(nt_x, nt_y, le_x, le_y, lm_x, lm_y) / fw
            if d_r < 0.015 and d_l < 0.015:
                return False

        return True

    @classmethod
    def assess(
        cls,
        crop: np.ndarray,
        fw: float,
        fh: float,
        landmarks: list[tuple[float, float]] | None,
        conf: float,
        conf_threshold: float = 0.45,
        min_size: float = 24.0,
    ) -> FaceQuality:
        """Assess facial quality including landmark geometry, blur, and illumination."""
        if crop.size > 0:
            gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
            blur = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
            illumination = float(np.mean(gray_crop))
        else:
            blur = 0.0
            illumination = 0.0

        if landmarks and len(landmarks) >= 3:
            re_x, le_x, nt_x = landmarks[0][0], landmarks[1][0], landmarks[2][0]
            eye_dist = abs(le_x - re_x)
            eye_mid = (re_x + le_x) / 2.0
            pose_yaw = float((nt_x - eye_mid) / (eye_dist + 1e-6) * 90.0) if eye_dist > 0 else 0.0
        else:
            pose_yaw = 0.0

        geometry_valid = cls.validate_geometry(fw, fh, landmarks, min_size=min_size)
        passed = bool(
            geometry_valid
            and blur >= 10.0
            and 15.0 <= illumination <= 245.0
            and conf >= conf_threshold
        )

        return FaceQuality(
            blur=blur,
            pose_yaw=pose_yaw,
            occlusion=0.0,
            illumination=illumination,
            passed=passed,
            geometry_valid=geometry_valid,
        )


def validate_facial_geometry(
    fw: float,
    fh: float,
    landmarks: list[tuple[float, float]] | None,
    min_size: float = 24.0,
) -> bool:
    """Validate 5-point facial landmarks for plausible human facial geometry."""
    return FaceQualityAssessment.validate_geometry(fw, fh, landmarks, min_size=min_size)


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
        conf_threshold: float = 0.45,
    ) -> None:
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self._detector: cv2.FaceDetectorYN | None = None

        p = pathlib.Path(model_path)
        if p.exists() and hasattr(cv2, "FaceDetectorYN"):
            if hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            try:
                backend = cv2.dnn.DNN_BACKEND_OPENCV
                target = cv2.dnn.DNN_TARGET_OPENCL if cv2.ocl.haveOpenCL() else cv2.dnn.DNN_TARGET_CPU
                self._detector = cv2.FaceDetectorYN.create(
                    str(p),
                    "",
                    (320, 320),
                    score_threshold=conf_threshold,
                    nms_threshold=0.3,
                    top_k=5000,
                    backend_id=backend,
                    target_id=target,
                )
            except Exception:
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
            else:
                crop = np.empty((0, 0, 3), dtype=np.uint8)

            quality = FaceQualityAssessment.assess(
                crop=crop,
                fw=fw,
                fh=fh,
                landmarks=landmarks,
                conf=conf,
                conf_threshold=self.conf_threshold,
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
    against enrolled suspect templates.
    """

    def __init__(self, model_path: str = "models/face_recognition_sface_2021dec.onnx") -> None:
        self.model_path = model_path
        self._recognizer: cv2.FaceRecognizerSF | None = None

        p = pathlib.Path(model_path)
        if p.exists() and hasattr(cv2, "FaceRecognizerSF"):
            if hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            try:
                self._recognizer = cv2.FaceRecognizerSF.create(str(p), "")
            except Exception:
                self._recognizer = None

    def align_crop(self, frame: np.ndarray, face_row: np.ndarray | FaceDetection) -> np.ndarray:
        """Warp and align detected face to standard 112x112 portrait using 5 landmarks."""
        if self._recognizer is None or frame.size == 0:
            return np.zeros((112, 112, 3), dtype=np.uint8)

        if isinstance(face_row, FaceDetection):
            if not face_row.quality.passed:
                return np.zeros((112, 112, 3), dtype=np.uint8)
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
        if self._recognizer is None or aligned_crop.size == 0 or np.all(aligned_crop == 0):
            return np.zeros((1, 128), dtype=np.float32)

        if aligned_crop.shape[:2] != (112, 112):
            aligned_crop = cv2.resize(aligned_crop, (112, 112))

        try:
            feat = self._recognizer.feature(aligned_crop)
            arr = np.asarray(feat, dtype=np.float32)
            if not np.all(np.isfinite(arr)):
                return np.zeros((1, 128), dtype=np.float32)
            return arr
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
