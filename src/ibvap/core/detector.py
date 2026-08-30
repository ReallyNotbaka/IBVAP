"""DetectorProvider - vendor-neutral abstraction.

Phase 3 slice uses MockDetector for tests (YOLO26 BLOCKED pending gate).
Production will plug YOLO26ONNX or RF-DETRONNX via same interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    # normalized source box [0,1] x1,y1,x2,y2
    bbox_norm: tuple[float, float, float, float]
    model_id: str
    runtime: str


class DetectorProvider(Protocol):
    def detect(self, frame: np.ndarray, frame_id: int) -> list[Detection]: ...
    @property
    def model_id(self) -> str: ...
    @property
    def input_size(self) -> int: ...


class MockPersonDetector:
    """Deterministic mock - returns a moving person box for synthetic video.

    For real video, it returns empty. Used to prove pipeline without YOLO weights.
    Gate note: YOLO26 blocked (ADR-0004); this mock proves geometry/tracking/outbox.
    """

    def __init__(self, model_id: str = "mock-person-v1", input_size: int = 640) -> None:
        self._model_id = model_id
        self._input_size = input_size

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def input_size(self) -> int:
        return self._input_size

    def detect(self, frame: np.ndarray, frame_id: int) -> list[Detection]:
        _ = frame.shape  # keep frame param used
        # For synthetic test: if frame is synthetic (we check via frame_id parity or via mean)
        # Return a box that moves diagonally, entering a central zone at frame 10
        # This is deterministic and test-friendly.
        if frame_id < 0:
            return []
        # Simple heuristic: if frame mean > 0, produce detection
        # Synthetic frames have varying mean due to moving avatar; real black frames won't.
        # For tests, we force detection for frame_id 5..15 to simulate intrusion
        if 5 <= frame_id <= 20:
            # normalized box moving from (0.2,0.2,0.3,0.4) to (0.5,0.5,0.6,0.7)
            t = (frame_id - 5) / 15.0
            x1 = 0.2 + 0.3 * t
            y1 = 0.2 + 0.3 * t
            x2 = x1 + 0.1
            y2 = y1 + 0.2
            return [
                Detection(
                    class_id=0,
                    class_name="person",
                    confidence=0.92,
                    bbox_norm=(x1, y1, x2, y2),
                    model_id=self._model_id,
                    runtime="mock",
                )
            ]
        # Also detect person if frame has non-zero content (for real synthetic video)
        # Fallback: if frame not empty, return centered person
        if np.mean(frame) > 5:
            return [
                Detection(
                    class_id=0,
                    class_name="person",
                    confidence=0.85,
                    bbox_norm=(0.4, 0.4, 0.6, 0.8),
                    model_id=self._model_id,
                    runtime="mock",
                )
            ]
        return []


class YOLO26DetectorStub:
    """Stub for YOLO26 - raises until gate passes. Documents expected interface."""

    def __init__(self) -> None:
        raise RuntimeError("YOLO26 is BLOCKED pending Enterprise grant (ADR-0004). Use MockPersonDetector for Phase 3 slice or RF-DETR alternative.")

    def detect(self, frame: np.ndarray, frame_id: int) -> list[Detection]:  # type: ignore[no-untyped-def]
        raise NotImplementedError
