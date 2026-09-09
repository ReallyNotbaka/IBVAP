"""Night movement - Phase 4, spec 14."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class NightResult:
    is_night: bool
    illumination_score: float
    motion_area: float
    motion_persistence: int
    camera_motion: float
    confidence: float
    limitation: str


class NightDetector:
    def __init__(self, night_threshold: float = 40.0, day_threshold: float = 70.0, temporal_seconds: float = 5.0) -> None:
        self.night_threshold = night_threshold
        self.day_threshold = day_threshold
        self.temporal_seconds = temporal_seconds
        self._bg: np.ndarray | None = None
        self._last_switch = 0.0
        self._mode: str = "day"
        self._motion_history: list[float] = []
        # Cached structuring element: avoids a getStructuringElement alloc per frame.
        self._open_kernel: np.ndarray = np.ones((3, 3), np.uint8)

    @property
    def current_mode(self) -> str:
        return self._mode

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 3 and frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.ndim == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        return frame

    def _luminance(self, frame: np.ndarray) -> float:
        return self._luminance_from_gray(self._to_gray(frame))

    @staticmethod
    def _luminance_from_gray(gray: np.ndarray) -> float:
        mean_lum = float(np.mean(gray))
        # Percentile / dark-ratio stats run on a strided (zero-copy) view:
        # sorts and the boolean mask then touch ~4x fewer pixels. Exact for
        # uniform frames; a close approximation otherwise.
        small = gray[::2, ::2]
        p10 = float(np.percentile(small, 10))
        p50 = float(np.percentile(small, 50))

        # Gamma / contrast assessment: ratio of pixels in lower quartile
        dark_pixel_ratio = float(np.count_nonzero(small < 45)) / max(1, small.size)

        # Composite illumination score:
        # If the majority of the frame is dark (>60% dark pixels), headlights/torches shouldn't fool it into day
        composite = 0.50 * p10 + 0.35 * p50 + 0.15 * mean_lum if dark_pixel_ratio > 0.65 else 0.40 * p50 + 0.35 * mean_lum + 0.25 * p10

        return float(np.clip(composite, 0.0, 255.0))

    def update(self, frame: np.ndarray, timestamp: float | None = None) -> NightResult:
        # Single BGR->gray conversion per frame, shared by the luminance and
        # motion paths (previously converted twice).
        gray = self._to_gray(frame)
        lum = self._luminance_from_gray(gray)
        now = timestamp if timestamp is not None else 0.0
        if self._mode == "day" and lum < self.night_threshold and (now - self._last_switch) >= self.temporal_seconds:
            self._mode = "night"
            self._last_switch = now
        elif self._mode == "night" and lum > self.day_threshold and (now - self._last_switch) >= self.temporal_seconds:
            self._mode = "day"
            self._last_switch = now

        gray_f = gray.astype(np.float32)
        if self._bg is None or self._bg.shape != gray_f.shape:
            self._bg = gray_f
        else:
            cv2.accumulateWeighted(gray_f, self._bg, 0.02)

        diff = cv2.absdiff(gray_f, self._bg)  # type: ignore[arg-type]
        # Night threshold 12 (day stays 25): calibrated from the response
        # curve - dark-clothed movers (contrast ~14-16) vanish above ~20,
        # while static sensor grain and global illumination steps still read
        # zero through the open+area+persistence gates. See test_night_*.
        threshold_val = 12 if self._mode == "night" else 25
        _, thresh = cv2.threshold(diff, threshold_val, 255, cv2.THRESH_BINARY)
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self._open_kernel)
        motion_pixels = int(np.count_nonzero(cleaned))
        total = frame.shape[0] * frame.shape[1]
        motion_area = motion_pixels / max(1, total)
        self._motion_history.append(motion_area)
        if len(self._motion_history) > 10:
            self._motion_history.pop(0)
        persistence = sum(1 for v in self._motion_history if v > 0.005)
        camera_motion = 0.0
        confidence = 0.7 if motion_area > 0.01 and persistence >= 3 else 0.3 if motion_area > 0 else 0.0

        if self._mode == "night":
            if lum < 15.0:
                limitation = "severe low visibility (<15 lux)"
            elif lum < 30.0:
                limitation = "low visibility (<30 lux)"
            else:
                limitation = "night operational"
        else:
            limitation = "none"

        return NightResult(
            is_night=self._mode == "night",
            illumination_score=round(lum, 1),
            motion_area=round(motion_area, 4),
            motion_persistence=persistence,
            camera_motion=camera_motion,
            confidence=confidence,
            limitation=limitation,
        )
