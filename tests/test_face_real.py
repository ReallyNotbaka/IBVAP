from __future__ import annotations

import numpy as np
import pytest

from ibvap.config import AppConfig, Settings
from ibvap.core.face import (
    FaceDetection,
    FaceDetector,
    FaceQuality,
    FaceRecognizer,
    check_identity_gate_passed,
)


def test_face_detector_init_and_blank_frame() -> None:
    detector = FaceDetector(model_path="models/face_detection_yunet_2023mar.onnx")
    assert detector._detector is not None

    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = detector.detect(blank)
    assert dets == []


def test_face_detector_nonexistent_model() -> None:
    detector = FaceDetector(model_path="models/nonexistent_model.onnx")
    assert detector._detector is None
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    assert detector.detect(blank) == []


def test_face_detector_with_mock_detection() -> None:
    detector = FaceDetector(model_path="models/face_detection_yunet_2023mar.onnx")
    assert detector._detector is not None

    # Mock detector._detector to return a synthetic face row
    h, w = 480, 640
    frame = np.ones((h, w, 3), dtype=np.uint8) * 120
    # Add some texture for laplacian blur
    frame[100:200, 100:200] = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)

    # Face row: x=100, y=100, w=100, h=100, right_eye=(125, 130), left_eye=(175, 130), nose=(150, 155), right_mouth=(135, 180), left_mouth=(165, 180), conf=0.85
    mock_face_row = np.array(
        [[100.0, 100.0, 100.0, 100.0, 125.0, 130.0, 175.0, 130.0, 150.0, 155.0, 135.0, 180.0, 165.0, 180.0, 0.85]],
        dtype=np.float32,
    )

    class MockDetector:
        def setInputSize(self, size: tuple[int, int]) -> None:
            pass

        def detect(self, img: np.ndarray) -> tuple[int, np.ndarray]:
            return 1, mock_face_row

    detector._detector = MockDetector()  # type: ignore[assignment]

    dets = detector.detect(frame)
    assert len(dets) == 1
    det = dets[0]
    assert isinstance(det, FaceDetection)
    assert det.confidence == pytest.approx(0.85)
    # Bbox normalized [0, 1]
    assert det.bbox_norm == pytest.approx((100 / 640, 100 / 480, 200 / 640, 200 / 480))
    # Check landmarks
    assert det.landmarks is not None
    assert len(det.landmarks) == 5
    assert det.landmarks[0] == (125.0, 130.0)
    # Quality metrics
    assert isinstance(det.quality, FaceQuality)
    assert det.quality.illumination > 0.0
    assert det.quality.blur > 0.0
    assert det.quality.passed is True


def test_face_recognizer_init_and_feature_extraction() -> None:
    recognizer = FaceRecognizer(model_path="models/face_recognition_sface_2021dec.onnx")
    assert recognizer._recognizer is not None

    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    feat = recognizer.extract_feature(crop)
    assert feat.shape == (1, 128)
    assert feat.dtype == np.float32


def test_face_recognizer_nonexistent_model() -> None:
    recognizer = FaceRecognizer(model_path="models/nonexistent_model.onnx")
    assert recognizer._recognizer is None
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    feat = recognizer.extract_feature(crop)
    assert feat.shape == (1, 128)
    assert np.all(feat == 0)
    assert recognizer.match(feat, feat) == 0.0


def test_face_recognizer_align_crop() -> None:
    recognizer = FaceRecognizer(model_path="models/face_recognition_sface_2021dec.onnx")
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    face_row = np.array(
        [100.0, 100.0, 100.0, 100.0, 125.0, 130.0, 175.0, 130.0, 150.0, 155.0, 135.0, 180.0, 165.0, 180.0, 0.85],
        dtype=np.float32,
    )
    aligned = recognizer.align_crop(frame, face_row)
    assert aligned.shape == (112, 112, 3)


def test_face_recognizer_match_and_identify() -> None:
    recognizer = FaceRecognizer(model_path="models/face_recognition_sface_2021dec.onnx")
    # Synthetic face crops
    crop1 = np.ones((112, 112, 3), dtype=np.uint8) * 50
    crop2 = np.ones((112, 112, 3), dtype=np.uint8) * 200

    feat1 = recognizer.extract_feature(crop1)
    feat2 = recognizer.extract_feature(crop2)

    # Identical features have cosine similarity close to 1.0
    sim_self = recognizer.match(feat1, feat1)
    assert sim_self >= 0.99

    watchlist = {
        "person_alpha": feat1,
        "person_beta": feat2,
    }

    match_id, score = recognizer.identify(feat1, watchlist, threshold=0.363)
    assert match_id == "person_alpha"
    assert score >= 0.99

    # Identity not in watchlist or below threshold
    feat_unseen = np.random.randn(1, 128).astype(np.float32)
    match_id_low, _ = recognizer.match_identity(feat_unseen, watchlist, threshold=0.999)
    assert match_id_low is None


def test_identity_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. Default disabled
    monkeypatch.delenv("IBVAP_ENABLE_FACE_IDENTITY", raising=False)
    monkeypatch.delenv("IBVAP_APP__ENABLE_FACE_IDENTITY", raising=False)
    assert check_identity_gate_passed() is False
    assert FaceDetector.check_identity_gate_passed() is False

    # 2. Enabled via settings
    cfg = AppConfig(enable_face_identity=True)
    assert check_identity_gate_passed(cfg) is True

    settings = Settings(app=AppConfig(enable_face_identity=True))
    assert check_identity_gate_passed(settings) is True
    assert FaceDetector.check_identity_gate_passed(settings) is True

    # 3. Enabled via env var
    monkeypatch.setenv("IBVAP_ENABLE_FACE_IDENTITY", "1")
    assert check_identity_gate_passed() is True
    assert FaceDetector.check_identity_gate_passed() is True


def test_face_geometry_validation_and_quality() -> None:
    from ibvap.core.face import FaceQualityAssessment, validate_facial_geometry
    from ibvap.core.watchlist import is_valid_exemplar

    # Normal valid face landmarks
    valid_landmarks = [
        (125.0, 130.0),  # right eye
        (175.0, 130.0),  # left eye
        (150.0, 155.0),  # nose tip
        (135.0, 180.0),  # right mouth corner
        (165.0, 180.0),  # left mouth corner
    ]
    assert validate_facial_geometry(100.0, 100.0, valid_landmarks) is True

    # 1. Inverted eyes (re_x >= le_x)
    inverted_eyes = [(175.0, 130.0), (125.0, 130.0), (150.0, 155.0), (135.0, 180.0), (165.0, 180.0)]
    assert validate_facial_geometry(100.0, 100.0, inverted_eyes) is False

    # 2. Inverted mouth (rm_x >= lm_x)
    inverted_mouth = [(125.0, 130.0), (175.0, 130.0), (150.0, 155.0), (165.0, 180.0), (135.0, 180.0)]
    assert validate_facial_geometry(100.0, 100.0, inverted_mouth) is False

    # 3. Extreme roll tilt (> 0.70)
    tilted_eyes = [(125.0, 100.0), (145.0, 180.0), (135.0, 140.0), (130.0, 160.0), (150.0, 160.0)]
    assert validate_facial_geometry(100.0, 100.0, tilted_eyes) is False

    # 4. Nose above eyes
    nose_above = [(125.0, 130.0), (175.0, 130.0), (150.0, 110.0), (135.0, 180.0), (165.0, 180.0)]
    assert validate_facial_geometry(100.0, 100.0, nose_above) is False

    # 5. Degenerate collinear landmarks (all on a line)
    collinear = [(100.0, 100.0), (100.0, 120.0), (100.0, 140.0), (100.0, 160.0), (100.0, 180.0)]
    assert validate_facial_geometry(100.0, 100.0, collinear) is False

    # 6. None or too few landmarks
    assert validate_facial_geometry(100.0, 100.0, None) is False
    assert validate_facial_geometry(100.0, 100.0, [(125.0, 130.0)]) is False

    # Assess quality method test
    crop = np.ones((100, 100, 3), dtype=np.uint8) * 128
    q_valid = FaceQualityAssessment.assess(crop, 100.0, 100.0, valid_landmarks, conf=0.8)
    assert q_valid.geometry_valid is True

    # Exemplar validation
    rng = np.random.default_rng(123)
    good_vec = rng.standard_normal(128).astype(np.float32)
    assert is_valid_exemplar(good_vec) is True

    # Bad exemplars
    assert is_valid_exemplar(np.zeros(128, dtype=np.float32)) is False
    assert is_valid_exemplar(np.ones(128, dtype=np.float32)) is False
    assert is_valid_exemplar(np.array([np.nan] * 128, dtype=np.float32)) is False
    assert is_valid_exemplar(np.ones(64, dtype=np.float32)) is False

