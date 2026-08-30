from __future__ import annotations

import cv2
import numpy as np

from ibvap.core.anpr import ANPRPipeline, OCRReader, PlateDetector, PlateResult, normalize_plate


def test_normalize_plate_diverse_inputs() -> None:
    assert normalize_plate("mh 01 ab 1234") == "MH01AB1234"
    assert normalize_plate("dl-8c-aa-1111") == "DL8CAA1111"
    assert normalize_plate("KA.05.NB.9999") == "KA05NB9999"
    assert normalize_plate("abc-123") == "ABC123"
    assert normalize_plate("AB12") == "AB12"
    assert normalize_plate("!!!") == ""
    assert normalize_plate("   ") == ""


def test_plate_detector_empty_and_blank_crops() -> None:
    detector = PlateDetector()

    # Empty array
    assert detector.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []

    # Tiny crop below minimum dimensions
    assert detector.detect(np.zeros((10, 10, 3), dtype=np.uint8)) == []

    # Blank solid color crop
    blank = np.full((200, 300, 3), 128, dtype=np.uint8)
    assert detector.detect(blank) == []


def test_plate_detector_synthetic_plate_localization() -> None:
    detector = PlateDetector()

    # Synthetic vehicle crop (h=200, w=300) with plate at (75, 130) to (225, 170)
    # Plate size: w=150, h=40, aspect=3.75, area=6000 (10% of total area)
    vehicle_crop = np.full((200, 300, 3), 100, dtype=np.uint8)
    cv2.rectangle(vehicle_crop, (75, 130), (225, 170), (240, 240, 240), -1)
    cv2.rectangle(vehicle_crop, (75, 130), (225, 170), (20, 20, 20), 2)
    cv2.putText(vehicle_crop, "MH01AB1234", (80, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (10, 10, 10), 2)

    boxes = detector.detect(vehicle_crop)
    assert len(boxes) >= 1

    x1_n, y1_n, x2_n, y2_n = boxes[0]
    # Check normalized bounds are reasonable approximations of the synthetic plate
    assert 0.15 <= x1_n <= 0.35
    assert 0.55 <= y1_n <= 0.75
    assert 0.65 <= x2_n <= 0.85
    assert 0.75 <= y2_n <= 0.95


def test_ocr_reader_quality_gate() -> None:
    ocr = OCRReader()

    # Uniform image has 0 Laplacian variance
    flat_img = np.full((40, 150, 3), 200, dtype=np.uint8)
    assert ocr.check_quality(flat_img) < 10.0
    assert ocr.recognize(flat_img) == []

    # Blurred / low contrast plate
    blurred = cv2.GaussianBlur(flat_img, (15, 15), 0)
    assert ocr.check_quality(blurred) < 10.0
    assert ocr.recognize(blurred) == []


def test_ocr_reader_recognition() -> None:
    ocr = OCRReader()

    # Synthetic plate crop
    plate_crop = np.full((40, 160, 3), 240, dtype=np.uint8)
    cv2.putText(plate_crop, "MH12DE1234", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (15, 15, 15), 2)

    assert ocr.check_quality(plate_crop) >= 10.0
    candidates = ocr.recognize(plate_crop)
    assert len(candidates) >= 1
    assert len(candidates[0].text) >= 4
    assert candidates[0].confidence > 0.0


def test_multiframe_temporal_consensus() -> None:
    pipeline = ANPRPipeline()

    # Feed sequence with noise
    stream = ["MH01AB1234", "MH01AB1234", "MH01AB123X", "MH01AB1234", "MH01AB1234"]
    consensus = ""
    for item in stream:
        consensus = pipeline.consensus_for(vehicle_id=1, text=item)
    assert consensus == "MH01AB1234"

    # Test sliding window shift: feed 12 new items
    for _ in range(12):
        consensus = pipeline.consensus_for(vehicle_id=1, text="KA05NB9999")
    assert consensus == "KA05NB9999"


def test_anpr_pipeline_end_to_end() -> None:
    pipeline = ANPRPipeline()

    vehicle_crop = np.full((200, 300, 3), 90, dtype=np.uint8)
    cv2.rectangle(vehicle_crop, (75, 130), (225, 170), (240, 240, 240), -1)
    cv2.rectangle(vehicle_crop, (75, 130), (225, 170), (20, 20, 20), 2)
    cv2.putText(vehicle_crop, "MH01AB1234", (80, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (10, 10, 10), 2)

    result = pipeline.process_vehicle_crop(vehicle_crop, vehicle_id=42)
    assert result is not None
    assert isinstance(result, PlateResult)
    assert len(result.plate_text) >= 4
    assert result.consensus is not None
    assert len(result.candidates) >= 1
    assert result.quality >= 10.0


def test_anpr_pipeline_empty_and_blank() -> None:
    pipeline = ANPRPipeline()

    assert pipeline.process_vehicle_crop(np.zeros((0, 0, 3), dtype=np.uint8), vehicle_id=1) is None

    blank = np.full((200, 300, 3), 100, dtype=np.uint8)
    assert pipeline.process_vehicle_crop(blank, vehicle_id=1) is None
