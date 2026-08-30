from __future__ import annotations

import numpy as np

from ibvap.core.anpr import normalize_plate
from ibvap.core.face import FaceDetector


def test_face_detector_does_not_fabricate() -> None:
    fd = FaceDetector(model_path="nonexistent.onnx")
    blank = np.zeros((100, 100, 3), dtype=np.uint8)
    assert fd.detect(blank) == []
    assert FaceDetector.check_identity_gate_passed() is False


def test_anpr_normalization() -> None:
    assert normalize_plate("mh 01 ab 1234") == "MH01AB1234"
    assert normalize_plate("abc-123") == "ABC123"
    # invalid remains as raw for review, not forced
    assert normalize_plate("!!!") == ""
