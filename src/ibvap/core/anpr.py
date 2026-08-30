"""ANPR - Automated Number Plate Recognition.

Morphological plate localization + OCR text recognition + multi-frame consensus.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
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
    """Normalize plate text by removing non-alphanumerics and converting to uppercase."""
    t = re.sub(r"[^A-Z0-9]", "", text.upper())
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
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

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
    """Character segmentation and template/morphological text recognition for plate crops."""

    def __init__(
        self,
        ocr_engine: Callable[[np.ndarray], list[PlateCandidate]] | None = None,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.templ_w = 20
        self.templ_h = 28
        self.templates = self._build_templates()

    def _build_templates(self) -> dict[str, list[np.ndarray]]:
        """Pre-compute normalized character glyph templates for fast matching."""
        templates: dict[str, list[np.ndarray]] = {}
        for ch in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            t_list: list[np.ndarray] = []
            for font in (cv2.FONT_HERSHEY_SIMPLEX, cv2.FONT_HERSHEY_DUPLEX):
                for scale in (0.7, 1.0):
                    for thick in (1, 2):
                        timg = np.zeros((80, 80), dtype=np.uint8)
                        cv2.putText(timg, ch, (15, 60), font, scale, 255, thick)
                        cnts, _ = cv2.findContours(timg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        if cnts:
                            x, y, w, h = cv2.boundingRect(max(cnts, key=cv2.contourArea))
                            if w > 0 and h > 0:
                                glyph = timg[y : y + h, x : x + w]
                                t_list.append(cv2.resize(glyph, (self.templ_w, self.templ_h)))
            templates[ch] = t_list
        return templates

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

        if len(plate_crop.shape) == 3 and plate_crop.shape[2] == 3:
            gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
        elif len(plate_crop.shape) == 3 and plate_crop.shape[2] == 1:
            gray = plate_crop[:, :, 0]
        else:
            gray = plate_crop

        mean_val = float(np.mean(gray))
        if mean_val > 120:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        else:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        cnts, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        ch, cw = plate_crop.shape[:2]

        char_boxes: list[tuple[int, int, int, int]] = []
        for c in cnts:
            cx, cy, cbw, cbh = cv2.boundingRect(c)
            if 0.20 * ch <= cbh <= 0.98 * ch and 3 <= cbw <= 0.40 * cw and (cbw * cbh) < (0.75 * ch * cw):
                char_boxes.append((cx, cy, cbw, cbh))

        # Filter nested bounding boxes (e.g. holes inside 0, 8, B, D)
        filtered_boxes: list[tuple[int, int, int, int]] = []
        for i, b1 in enumerate(char_boxes):
            contained = False
            for j, b2 in enumerate(char_boxes):
                if i != j and b1[0] >= b2[0] and b1[1] >= b2[1] and (b1[0] + b1[2]) <= (b2[0] + b2[2]) and (b1[1] + b1[3]) <= (b2[1] + b2[3]):
                    contained = True
                    break
            if not contained:
                filtered_boxes.append(b1)

        # Sort characters left-to-right
        filtered_boxes.sort(key=lambda b: b[0])
        if len(filtered_boxes) < 4:
            return []

        chars: list[str] = []
        confs: list[float] = []

        for cx, cy, cbw, cbh in filtered_boxes:
            char_crop = binary[cy : cy + cbh, cx : cx + cbw]
            char_resized = cv2.resize(char_crop, (self.templ_w, self.templ_h))

            best_char = "?"
            best_score = -1.0
            for ch_name, t_arrs in self.templates.items():
                for templ in t_arrs:
                    res = cv2.matchTemplate(char_resized, templ, cv2.TM_CCOEFF_NORMED)
                    score = float(res[0][0])
                    if score > best_score:
                        best_score = score
                        best_char = ch_name

            chars.append(best_char)
            confs.append(max(0.0, best_score))

        raw_text = "".join(chars)
        avg_conf = float(np.mean(confs)) if confs else 0.0

        return [
            PlateCandidate(
                text=raw_text,
                confidence=avg_conf,
                quality=quality,
                bbox_norm=(0.0, 0.0, 1.0, 1.0),
            )
        ]


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

    def consensus_for(self, vehicle_id: int, text: str) -> str:
        """Maintain sliding window of last 10 reads and return majority vote consensus."""
        norm = normalize_plate(text)
        val = norm if norm else text
        hist = self._history.setdefault(vehicle_id, [])
        hist.append(val)
        if len(hist) > 10:
            hist.pop(0)
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
                    cand_box = (
                        max(0.0, min(1.0, (bx1 + cand.bbox_norm[0] * (bx2 - bx1)) / w)),
                        max(0.0, min(1.0, (by1 + cand.bbox_norm[1] * (by2 - by1)) / h)),
                        max(0.0, min(1.0, (bx1 + cand.bbox_norm[2] * (bx2 - bx1)) / w)),
                        max(0.0, min(1.0, (by1 + cand.bbox_norm[3] * (by2 - by1)) / h)),
                    )
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
                        cand_box = (
                            max(0.0, min(1.0, (x1 + cand.bbox_norm[0] * (x2 - x1)) / w)),
                            max(0.0, min(1.0, (y1 + cand.bbox_norm[1] * (y2 - y1)) / h)),
                            max(0.0, min(1.0, (x1 + cand.bbox_norm[2] * (x2 - x1)) / w)),
                            max(0.0, min(1.0, (y1 + cand.bbox_norm[3] * (y2 - y1)) / h)),
                        )
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
