from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from ibvap.core.detector import (
    SECURITY_CLASSES,
    Detection,
    MockPersonDetector,
    ONNXDetectorProvider,
)
from ibvap.core.pipeline import MiniPipeline
from ibvap.events.outbox import clear_all, list_events


@pytest.mark.slow
def test_onnx_detector_initialization_and_properties(shared_onnx_detector: ONNXDetectorProvider) -> None:
    detector = shared_onnx_detector
    assert detector.model_id == "yolo26n"
    assert detector.input_size == 640
    assert detector.runtime in ("directml", "cpu")


def test_onnx_detector_blank_frame_returns_empty(shared_onnx_detector: ONNXDetectorProvider) -> None:
    detector = shared_onnx_detector
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = detector.detect(blank, frame_id=0)
    assert isinstance(dets, list)
    assert len(dets) == 0


def test_onnx_detector_empty_frame_handling(shared_onnx_detector: ONNXDetectorProvider) -> None:
    detector = shared_onnx_detector
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    dets = detector.detect(empty, frame_id=0)
    assert dets == []


def test_onnx_detector_preprocessing_letterbox(shared_onnx_detector: ONNXDetectorProvider) -> None:
    detector = shared_onnx_detector
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    blob, scale, pad_x, pad_y = detector._preprocess(frame)

    assert blob.shape == (1, 3, 640, 640)
    assert blob.dtype == np.float32
    assert scale == 1.0
    assert pad_x == 0.0
    assert pad_y == 80.0
    assert np.min(blob) >= 0.0
    assert np.max(blob) <= 1.0


def test_onnx_detector_simulated_detections_and_coordinate_bounds(
    shared_onnx_detector: ONNXDetectorProvider,
) -> None:
    detector = shared_onnx_detector

    # Create mock session output to verify parsing, NMS, and coordinate normalization
    # Shape: (1, 84, 8400)
    mock_out = np.zeros((1, 84, 8400), dtype=np.float32)

    # Box 1: person (class 0) at center [cx=320, cy=320, w=100, h=200], conf=0.9
    mock_out[0, 0, 10] = 320.0
    mock_out[0, 1, 10] = 320.0
    mock_out[0, 2, 10] = 100.0
    mock_out[0, 3, 10] = 200.0
    mock_out[0, 4, 10] = 0.9  # person class score (index 4 is class 0)

    # Box 2: car (class 2) at [cx=150, cy=200, w=80, h=60], conf=0.85
    mock_out[0, 0, 20] = 150.0
    mock_out[0, 1, 20] = 200.0
    mock_out[0, 2, 20] = 80.0
    mock_out[0, 3, 20] = 60.0
    mock_out[0, 6, 20] = 0.85  # car class score (index 6 is class 2)

    # Box 3: low confidence (< 0.35) bicycle (class 1)
    mock_out[0, 0, 30] = 400.0
    mock_out[0, 1, 30] = 400.0
    mock_out[0, 2, 30] = 50.0
    mock_out[0, 3, 30] = 50.0
    mock_out[0, 5, 30] = 0.20  # bicycle class score (index 5 is class 1)

    orig_run = detector._session.run
    detector._session.run = MagicMock(return_value=[mock_out])
    try:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dets = detector.detect(frame, frame_id=1)

        assert len(dets) == 2
        classes = {d.class_name for d in dets}
        assert "person" in classes
        assert "car" in classes
        assert "bicycle" not in classes

        for d in dets:
            assert isinstance(d, Detection)
            assert d.model_id == "yolo26n"
            assert d.runtime in ("directml", "cpu")
            x1, y1, x2, y2 = d.bbox_norm
            assert 0.0 <= x1 <= x2 <= 1.0
            assert 0.0 <= y1 <= y2 <= 1.0
            assert d.confidence >= 0.35
            assert d.class_id in SECURITY_CLASSES
    finally:
        detector._session.run = orig_run


def test_pipeline_with_onnx_detector() -> None:
    clear_all()
    # MiniPipeline should default to ONNXDetectorProvider when models/yolo26n.onnx exists
    pipe = MiniPipeline(camera_id="cam-onnx-test", stream_epoch=0)
    assert isinstance(pipe.detector, ONNXDetectorProvider)

    # Blank frame produces no intrusion events
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    ev = pipe.process_frame(blank)
    assert ev is None
    assert pipe.events_created == 0


def test_pipeline_explicit_detector_injection() -> None:
    clear_all()
    mock_detector = MockPersonDetector()
    pipe = MiniPipeline(camera_id="cam-mock-test", stream_epoch=0, detector=mock_detector)
    assert pipe.detector is mock_detector

    # Frame 10 with mock detector produces intrusion event
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    pipe.frame_idx = 10
    ev = pipe.process_frame(frame)
    assert ev is not None
    assert ev["event_type"] == "zone_intrusion"
    assert len(list_events()) == 1


def test_onnx_detector_class_aware_nms_preserves_colocated_classes(
    shared_onnx_detector: ONNXDetectorProvider,
) -> None:
    """Class-aware NMS must preserve co-located person and vehicle without inter-class suppression."""
    detector = shared_onnx_detector

    # Mock output with:
    # 1. Person at cx=320, cy=320, w=100, h=200, conf=0.92
    # 2. Duplicate Person at cx=322, cy=320, w=100, h=200, conf=0.70 (should be suppressed by box 1)
    # 3. Car at same location cx=320, cy=320, w=100, h=200, conf=0.88 (MUST NOT be suppressed by person)
    mock_out = np.zeros((1, 84, 8400), dtype=np.float32)

    # Box 1: Person (class 0 -> index 4)
    mock_out[0, :4, 0] = [320.0, 320.0, 100.0, 200.0]
    mock_out[0, 4, 0] = 0.92

    # Box 2: Duplicate Person (class 0 -> index 4)
    mock_out[0, :4, 1] = [322.0, 320.0, 100.0, 200.0]
    mock_out[0, 4, 1] = 0.70

    # Box 3: Car (class 2 -> index 6)
    mock_out[0, :4, 2] = [320.0, 320.0, 100.0, 200.0]
    mock_out[0, 6, 2] = 0.88

    orig_run = detector._session.run
    detector._session.run = MagicMock(return_value=[mock_out])
    try:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dets = detector.detect(frame, frame_id=1)

        # Must have exactly 2 detections: 1 person and 1 car (duplicate person suppressed, car preserved!)
        assert len(dets) == 2
        classes = [d.class_name for d in dets]
        assert classes.count("person") == 1
        assert classes.count("car") == 1
    finally:
        detector._session.run = orig_run


def test_onnx_detector_preprocessing_aspect_ratios_buffer_reuse(
    shared_onnx_detector: ONNXDetectorProvider,
) -> None:
    """Reusable canvas buffer must handle dynamic aspect ratios and frame sizes seamlessly."""
    detector = shared_onnx_detector

    # 1. 1080p landscape
    frame_1080 = np.ones((1080, 1920, 3), dtype=np.uint8) * 50
    blob1, scale1, pad_x1, pad_y1 = detector._preprocess(frame_1080)
    assert blob1.shape == (1, 3, 640, 640)
    assert pad_x1 == 0.0
    assert pad_y1 == 140.0

    # 2. 480p landscape
    frame_480 = np.ones((480, 640, 3), dtype=np.uint8) * 100
    blob2, scale2, pad_x2, pad_y2 = detector._preprocess(frame_480)
    assert blob2.shape == (1, 3, 640, 640)
    assert pad_x2 == 0.0
    assert pad_y2 == 80.0

    # 3. Portrait 9:16
    frame_portrait = np.ones((1280, 720, 3), dtype=np.uint8) * 150
    blob3, scale3, pad_x3, pad_y3 = detector._preprocess(frame_portrait)
    assert blob3.shape == (1, 3, 640, 640)
    assert pad_x3 == 140.0
    assert pad_y3 == 0.0
