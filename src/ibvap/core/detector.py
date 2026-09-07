"""DetectorProvider - vendor-neutral abstraction and ONNX implementation.

Provides DetectorProvider protocol, MockPersonDetector for testing,
and real ONNXDetectorProvider with DirectML and CPU execution providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import onnxruntime as ort

SECURITY_CLASSES: dict[int, str] = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


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


class ONNXDetectorProvider:
    """Real ONNX-based object detector (YOLO26 / YOLOv8 architecture).

    Supports DirectML acceleration on Windows with fallback to CPU.
    Filters detections to security classes (person, vehicles) with NMS and letterboxing.
    """

    def __init__(
        self,
        model_path: str = "models/yolo26n.onnx",
        conf_threshold: float = 0.48,
        iou_threshold: float = 0.45,
        input_size: int = 640,
        providers: list[str] | None = None,
    ) -> None:
        self._model_path = model_path
        self._conf_threshold = conf_threshold
        self._iou_threshold = iou_threshold
        self._input_size = input_size
        self._model_id = Path(model_path).stem
        self._canvas: np.ndarray = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
        self._last_pad_sig: tuple[int, int, int, int] | None = None

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.enable_mem_pattern = True
        sess_options.enable_cpu_mem_arena = True

        available = ort.get_available_providers()
        try:
            if providers is not None:
                dml_active = "DmlExecutionProvider" in providers
                prov_options = [{"device_id": 0} if p == "DmlExecutionProvider" else {} for p in providers] if dml_active else None
                self._session = ort.InferenceSession(
                    self._model_path,
                    sess_options=sess_options,
                    providers=providers,
                    provider_options=prov_options,
                )
            elif "DmlExecutionProvider" in available:
                self._session = ort.InferenceSession(
                    self._model_path,
                    sess_options=sess_options,
                    providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                    provider_options=[{"device_id": 0}, {}],
                )
            else:
                self._session = ort.InferenceSession(
                    self._model_path,
                    sess_options=sess_options,
                    providers=["CPUExecutionProvider"],
                )
            active = self._session.get_providers()
            self._runtime = "directml" if "DmlExecutionProvider" in active else "cpu"
        except Exception:
            try:
                if "DmlExecutionProvider" in available:
                    self._session = ort.InferenceSession(
                        self._model_path,
                        sess_options=sess_options,
                        providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                        provider_options=[{"device_id": 0}, {}],
                    )
                    active = self._session.get_providers()
                    self._runtime = "directml" if "DmlExecutionProvider" in active else "cpu"
                else:
                    self._session = ort.InferenceSession(
                        self._model_path,
                        sess_options=sess_options,
                        providers=["CPUExecutionProvider"],
                    )
                    self._runtime = "cpu"
            except Exception:
                self._session = ort.InferenceSession(
                    self._model_path,
                    providers=["CPUExecutionProvider"],
                )
                self._runtime = "cpu"

        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def input_size(self) -> int:
        return self._input_size

    @property
    def runtime(self) -> str:
        return self._runtime

    def _preprocess(self, frame: np.ndarray) -> tuple[np.ndarray, float, float, float]:
        """Letterbox to (input_size, input_size) preserving aspect ratio.

        Returns (blob, scale, pad_x, pad_y) where blob is float32 [1, 3, input_size, input_size].
        """
        orig_h, orig_w = frame.shape[:2]
        scale = min(self._input_size / orig_h, self._input_size / orig_w)
        new_unpad_w = int(round(orig_w * scale))
        new_unpad_h = int(round(orig_h * scale))
        dw = (self._input_size - new_unpad_w) / 2.0
        dh = (self._input_size - new_unpad_h) / 2.0

        top = int(round(dh - 0.1))
        left = int(round(dw - 0.1))

        if (
            self._canvas is None
            or self._canvas.shape != (self._input_size, self._input_size, 3)
        ):
            self._canvas = np.full((self._input_size, self._input_size, 3), 114, dtype=np.uint8)
            self._last_pad_sig = None

        pad_sig = (top, left, new_unpad_h, new_unpad_w)
        if self._last_pad_sig != pad_sig:
            self._canvas.fill(114)
            self._last_pad_sig = pad_sig

        target_slice = self._canvas[top : top + new_unpad_h, left : left + new_unpad_w]
        if (orig_w, orig_h) == (new_unpad_w, new_unpad_h):
            target_slice[:] = frame
        else:
            cv2.resize(frame, (new_unpad_w, new_unpad_h), dst=target_slice, interpolation=cv2.INTER_LINEAR)

        blob = cv2.dnn.blobFromImage(
            self._canvas,
            scalefactor=1.0 / 255.0,
            swapRB=True,
            crop=False,
        )
        return blob, scale, float(left), float(top)

    def detect(self, frame: np.ndarray, frame_id: int = 0) -> list[Detection]:
        """Run object detection on an image/frame.

        Returns list of Detection dataclasses with normalized bounding boxes [0, 1].
        """
        if frame.size == 0:
            return []

        orig_h, orig_w = frame.shape[:2]
        blob, scale, pad_x, pad_y = self._preprocess(frame)

        outputs = self._session.run(None, {self._input_name: blob})
        output: np.ndarray = np.asarray(outputs[0], dtype=np.float32)

        if output.ndim == 3:
            if output.shape[1] == 84:
                preds = np.transpose(output[0])
            elif output.shape[2] == 84:
                preds = output[0]
            else:
                preds = output[0]
        else:
            preds = output

        boxes = preds[:, :4]
        class_scores = preds[:, 4:]

        sec_class_ids = list(SECURITY_CLASSES.keys())
        sec_scores = class_scores[:, sec_class_ids]
        best_sec_local_idx = np.argmax(sec_scores, axis=1)
        best_sec_scores = np.max(sec_scores, axis=1)

        mask = best_sec_scores >= self._conf_threshold
        if not np.any(mask):
            return []

        valid_boxes = boxes[mask]
        valid_scores = best_sec_scores[mask]
        valid_class_ids = np.array(sec_class_ids, dtype=np.int32)[best_sec_local_idx[mask]]

        cx = valid_boxes[:, 0]
        cy = valid_boxes[:, 1]
        w = valid_boxes[:, 2]
        h = valid_boxes[:, 3]
        x1_lb = cx - w / 2.0
        y1_lb = cy - h / 2.0

        # Class-aware NMS: offset coordinates by class ID so detections of different security
        # classes (e.g., person near a car or riding a bicycle) do not falsely suppress each other.
        class_offsets = (valid_class_ids * 10000.0).astype(np.float32)
        boxes_for_nms = np.column_stack((x1_lb + class_offsets, y1_lb, w, h))
        indices = cv2.dnn.NMSBoxes(boxes_for_nms, valid_scores, self._conf_threshold, self._iou_threshold)
        if len(indices) == 0:
            return []

        detections: list[Detection] = []
        for idx in np.array(indices).flatten():
            i = int(idx)
            x1 = x1_lb[i]
            y1 = y1_lb[i]
            x2 = x1 + w[i]
            y2 = y1 + h[i]

            x1_orig = (x1 - pad_x) / scale
            y1_orig = (y1 - pad_y) / scale
            x2_orig = (x2 - pad_x) / scale
            y2_orig = (y2 - pad_y) / scale

            x1_norm = float(np.clip(x1_orig / orig_w, 0.0, 1.0))
            y1_norm = float(np.clip(y1_orig / orig_h, 0.0, 1.0))
            x2_norm = float(np.clip(x2_orig / orig_w, 0.0, 1.0))
            y2_norm = float(np.clip(y2_orig / orig_h, 0.0, 1.0))

            if x2_norm < x1_norm:
                x1_norm, x2_norm = x2_norm, x1_norm
            if y2_norm < y1_norm:
                y1_norm, y2_norm = y2_norm, y1_norm

            bw_norm = x2_norm - x1_norm
            bh_norm = y2_norm - y1_norm

            # Reject zero or degenerate boxes
            if bw_norm <= 0.005 or bh_norm <= 0.005:
                continue

            cid = int(valid_class_ids[i])
            cname = SECURITY_CLASSES.get(cid, "unknown")
            conf = float(valid_scores[i])

            # Person bounding box sanity checks:
            if cname == "person":
                # Reject boxes with unviable pixel dimensions
                if bh_norm * orig_h < 20.0 or bw_norm * orig_w < 10.0:
                    continue
                # Aspect ratio sanity: human body (standing, sitting, or lying down)
                hw_ratio = bh_norm / max(1e-5, bw_norm)
                if hw_ratio < 0.22 or hw_ratio > 5.5:
                    continue
                # Reject boxes covering virtually the entire frame
                if bw_norm > 0.94 and bh_norm > 0.90:
                    continue
                # Require confidence >= 0.50 for person detections
                if conf < 0.50:
                    continue

            detections.append(
                Detection(
                    class_id=cid,
                    class_name=cname,
                    confidence=conf,
                    bbox_norm=(x1_norm, y1_norm, x2_norm, y2_norm),
                    model_id=self._model_id,
                    runtime=self._runtime,
                )
            )

        return detections


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
