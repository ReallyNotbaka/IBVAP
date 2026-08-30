"""ANPR - Phase 6, spec 16.

Dedicated plate detector + PaddleOCR + multi-frame consensus.
Gate: dedicated detector pending; OCR is PaddleOCR 3.7.0 PP-OCRv6.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class PlateCandidate:
    text: str
    confidence: float
    quality: float
    bbox_norm: tuple[float, float, float, float]


@dataclass(frozen=True)
class PlateResult:
    plate_text: str
    candidates: list[PlateCandidate]
    consensus: str | None
    quality: float


_JURISDICTION_RE = re.compile(r"^[A-Z0-9]{4,10}$")


def normalize_plate(text: str) -> str:
    # jurisdiction-aware validation placeholder - strip invalid, handle O/0 I/1 via config
    t = re.sub(r"[^A-Z0-9]", "", text.upper())
    # do NOT force invalid into valid via regex - return as is if fails
    if not _JURISDICTION_RE.match(t):
        return t  # return raw for human review, don't invent
    return t


class PlateDetectorStub:
    """Stub - requires dedicated plate ONNX (fast-alpr YOLO). Returns empty to avoid fabrication."""

    def detect(self, vehicle_crop: np.ndarray) -> list[tuple[float, float, float, float]]:
        if vehicle_crop.size == 0:
            return []
        # real would run YOLO-nano plate detector on crop
        return []


class OCRStub:
    """Stub for PaddleOCR - would call paddleocr.PaddleOCR rec."""

    def recognize(self, plate_crop: np.ndarray) -> list[PlateCandidate]:
        if plate_crop.size == 0:
            return []
        # placeholder: no OCR without model - return empty (never invent text)
        return []


class ANPRPipeline:
    def __init__(self) -> None:
        self.detector = PlateDetectorStub()
        self.ocr = OCRStub()
        self._history: dict[int, list[str]] = {}  # vehicle_track_id -> texts

    def process_vehicle_crop(self, vehicle_crop: np.ndarray, vehicle_id: int) -> PlateResult | None:
        boxes = self.detector.detect(vehicle_crop)
        if not boxes:
            # heuristic fallback for test - treat lower half as plate candidate
            h, w = vehicle_crop.shape[:2]
            if h < 20 or w < 60:
                return None
            # take center lower slice
            y1, y2 = int(h * 0.6), int(h * 0.9)
            x1, x2 = int(w * 0.3), int(w * 0.7)
            plate_crop = vehicle_crop[y1:y2, x1:x2]
            # blur/quality gate
            gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
            blur = cv2.Laplacian(gray, cv2.CV_64F).var()
            if blur < 10:
                return None
            cands = self.ocr.recognize(plate_crop)
            if not cands:
                return None
            # for test harness, we generate a synthetic plate if OCR empty but crop valid
            # In real Phase 6, this would be OCR output; for now we keep empty to avoid fabrication
            return None
        # real path would OCR each box
        return None

    def consensus_for(self, vehicle_id: int, text: str) -> str:
        hist = self._history.setdefault(vehicle_id, [])
        hist.append(normalize_plate(text))
        if len(hist) > 10:
            hist.pop(0)
        return Counter(hist).most_common(1)[0][0] if hist else text
