"""Number plate reading. Finds the plate rect inside a vehicle crop,
runs OCR, votes across frames for a stable consensus string.
Skips tiny/low-res crops - OCR just hallucinates on those.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")


def normalize_plate(text: str) -> str:
    """Normalize plate text by removing non-alphanumerics and converting to uppercase."""
    t = _NON_ALNUM_RE.sub("", text.upper())
    if not _JURISDICTION_RE.match(t):
        return t  # Return raw alphanumeric representation
    return t


class PlateDetector:
    """Morphological license plate detector operating on vehicle crops."""

    def __init__(
        self,
        min_ar: float = 1.8,
        max_ar: float = 5.5,
        min_area_ratio: float = 0.008,
        max_area_ratio: float = 0.35,
    ) -> None:
        self.min_ar = min_ar
        self.max_ar = max_ar
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        # Cached kernel: avoids a getStructuringElement alloc per vehicle crop.
        self._close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))

    def detect(self, vehicle_crop: np.ndarray) -> list[tuple[float, float, float, float]]:
        """Localize plate candidates using morphological operations and vertical gradient energy.

        Returns list of normalized bounding boxes (x1, y1, x2, y2).
        """
        if vehicle_crop.size == 0 or len(vehicle_crop.shape) < 2:
            return []

        h, w = vehicle_crop.shape[:2]
        if h < 20 or w < 35:
            return []

        if len(vehicle_crop.shape) == 3 and vehicle_crop.shape[2] == 3:
            gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
        elif len(vehicle_crop.shape) == 3 and vehicle_crop.shape[2] == 1:
            gray = vehicle_crop[:, :, 0]
        else:
            gray = vehicle_crop

        # Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Sobel vertical gradient (dx=1, dy=0) highlights high-frequency vertical character edges
        sobel = cv2.Sobel(blurred, cv2.CV_16S, 1, 0, ksize=3)
        sobel = cv2.convertScaleAbs(sobel)

        # Otsu thresholding to binary image
        _, thresh = cv2.threshold(sobel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Morphological closing with rectangular kernel (17, 3) to merge characters into plate blob
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self._close_kernel)

        # Find external contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        total_area = float(w * h)
        boxes: list[tuple[float, float, float, float]] = []

        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bh < 10 or bw < 35:
                continue

            aspect = bw / float(bh)
            if not (self.min_ar <= aspect <= self.max_ar):
                continue

            area = float(bw * bh)
            area_ratio = area / total_area
            if not (self.min_area_ratio <= area_ratio <= self.max_area_ratio):
                continue

            x1_norm = max(0.0, min(1.0, float(x) / w))
            y1_norm = max(0.0, min(1.0, float(y) / h))
            x2_norm = max(0.0, min(1.0, float(x + bw) / w))
            y2_norm = max(0.0, min(1.0, float(y + bh) / h))
            boxes.append((x1_norm, y1_norm, x2_norm, y2_norm))

        # Sort candidate boxes by area descending
        boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
        return boxes


PlateDetectorStub = PlateDetector


class OCRReader:
    """PaddleOCR-backed text recognition for plate crops."""

    def __init__(
        self,
        ocr_engine: Callable[[np.ndarray], list[PlateCandidate]] | None = None,
        device: str | None = None,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.device = device or os.getenv("IBVAP_ANPR_DEVICE", "gpu:0")
        self._paddle_ocr: Any = None
        self._paddle_unavailable = False

    def check_quality(self, crop: np.ndarray) -> float:
        """Compute Laplacian blur variance as a sharpness/quality score."""
        if crop.size == 0 or len(crop.shape) < 2:
            return 0.0
        if len(crop.shape) == 3 and crop.shape[2] == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        elif len(crop.shape) == 3 and crop.shape[2] == 1:
            gray = crop[:, :, 0]
        else:
            gray = crop
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def recognize(self, plate_crop: np.ndarray) -> list[PlateCandidate]:
        """Recognize characters on a plate crop with quality gating."""
        if plate_crop.size == 0 or len(plate_crop.shape) < 2:
            return []

        quality = self.check_quality(plate_crop)
        if quality < 10.0:
            return []

        if self.ocr_engine is not None:
            return self.ocr_engine(plate_crop)

        if self._paddle_unavailable:
            return []

        try:
            if self._paddle_ocr is None:
                from paddleocr import PaddleOCR

                self._paddle_ocr = PaddleOCR(
                    lang="en",
                    device=self.device,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )

            results = self._paddle_ocr.predict(input=plate_crop)
        except Exception:
            self._paddle_unavailable = True
            return []
        candidates: list[PlateCandidate] = []
        for result in results:
            if isinstance(result, Mapping):
                data: Mapping[str, Any] = result
            else:
                json_value = getattr(result, "json", None)
                parsed = json_value() if callable(json_value) else json_value
                if not isinstance(parsed, Mapping):
                    continue
                data = parsed
            texts = data.get("rec_texts", [])
            scores = data.get("rec_scores", [])
            boxes = data.get("rec_boxes", [])
            for index, text in enumerate(texts):
                confidence = float(scores[index]) if index < len(scores) else 0.0
                box = boxes[index] if index < len(boxes) else None
                bbox_norm = self._normalize_box(box, plate_crop.shape[1], plate_crop.shape[0])
                candidates.append(PlateCandidate(normalize_plate(str(text)), confidence, quality, bbox_norm))
        return candidates

    @staticmethod
    def _normalize_box(box: Any, width: int, height: int) -> tuple[float, float, float, float]:
        if box is None:
            return (0.0, 0.0, 1.0, 1.0)
        coords = np.asarray(box).reshape(-1, 2)
        if len(coords) < 2:
            return (0.0, 0.0, 1.0, 1.0)
        x1, y1 = coords.min(axis=0)
        x2, y2 = coords.max(axis=0)
        return (
            max(0.0, min(1.0, float(x1) / width)),
            max(0.0, min(1.0, float(y1) / height)),
            max(0.0, min(1.0, float(x2) / width)),
            max(0.0, min(1.0, float(y2) / height)),
        )


OCRStub = OCRReader


class ANPRPipeline:
    """Full ANPR Pipeline: plate detection + character OCR + temporal consensus."""

    def __init__(
        self,
        detector: PlateDetector | None = None,
        ocr: OCRReader | None = None,
    ) -> None:
        self.detector = detector or PlateDetector()
        self.ocr = ocr or OCRReader()
        self._history: dict[int, list[str]] = {}

    @staticmethod
    def _remap_box(
        inner: tuple[float, float, float, float],
        ox1: int,
        oy1: int,
        ox2: int,
        oy2: int,
        w: int,
        h: int,
    ) -> tuple[float, float, float, float]:
        """Map a plate-relative normalized box into vehicle-crop normalized coords."""
        ow = ox2 - ox1
        oh = oy2 - oy1
        return (
            max(0.0, min(1.0, (ox1 + inner[0] * ow) / w)),
            max(0.0, min(1.0, (oy1 + inner[1] * oh) / h)),
            max(0.0, min(1.0, (ox1 + inner[2] * ow) / w)),
            max(0.0, min(1.0, (oy1 + inner[3] * oh) / h)),
        )

    def consensus_for(self, vehicle_id: int, text: str) -> str:
        """Maintain sliding window of last 10 reads and return majority vote consensus."""
        norm = normalize_plate(text)
        val = norm if norm else text
        hist = self._history.setdefault(vehicle_id, [])
        hist.append(val)
        if len(hist) > 10:
            hist.pop(0)
        if len(hist) == 1:
            return val
        return Counter(hist).most_common(1)[0][0] if hist else val

    def process_vehicle_crop(self, vehicle_crop: np.ndarray, vehicle_id: int) -> PlateResult | None:
        """Localize plate, extract candidates, score quality, and calculate consensus."""
        if vehicle_crop.size == 0 or len(vehicle_crop.shape) < 2:
            return None

        h, w = vehicle_crop.shape[:2]
        boxes = self.detector.detect(vehicle_crop)
        candidates: list[PlateCandidate] = []

        if boxes:
            for box in boxes:
                x1_n, y1_n, x2_n, y2_n = box
                bx1 = max(0, int(round(x1_n * w)))
                by1 = max(0, int(round(y1_n * h)))
                bx2 = min(w, int(round(x2_n * w)))
                by2 = min(h, int(round(y2_n * h)))

                if bx2 <= bx1 or by2 <= by1:
                    continue

                plate_crop = vehicle_crop[by1:by2, bx1:bx2]
                cands = self.ocr.recognize(plate_crop)
                for cand in cands:
                    cand_box = self._remap_box(cand.bbox_norm, bx1, by1, bx2, by2, w, h)
                    candidates.append(
                        PlateCandidate(
                            text=cand.text,
                            confidence=cand.confidence,
                            quality=cand.quality,
                            bbox_norm=cand_box,
                        )
                    )
        else:
            # Center-lower heuristic crop fallback
            if h >= 20 and w >= 60:
                y1, y2 = int(h * 0.6), int(h * 0.9)
                x1, x2 = int(w * 0.3), int(w * 0.7)
                plate_crop = vehicle_crop[y1:y2, x1:x2]
                if plate_crop.size > 0:
                    cands = self.ocr.recognize(plate_crop)
                    for cand in cands:
                        cand_box = self._remap_box(cand.bbox_norm, x1, y1, x2, y2, w, h)
                        candidates.append(
                            PlateCandidate(
                                text=cand.text,
                                confidence=cand.confidence,
                                quality=cand.quality,
                                bbox_norm=cand_box,
                            )
                        )

        valid_cands: list[tuple[PlateCandidate, str]] = []
        for c in candidates:
            norm_text = normalize_plate(c.text)
            if len(norm_text) >= 4:
                valid_cands.append((c, norm_text))

        if not valid_cands:
            return None

        best_cand, best_text = max(valid_cands, key=lambda pair: (pair[0].confidence, pair[0].quality))
        consensus_text = self.consensus_for(vehicle_id, best_text)

        return PlateResult(
            plate_text=best_text,
            candidates=candidates,
            consensus=consensus_text,
            quality=best_cand.quality,
        )
