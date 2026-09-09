"""Person/vehicle detection. ONNX YOLO under the hood.

Tries DirectML first (Windows GPU), falls back to CPU if that's missing.
Only keeps security classes - person, car, bus, truck, bike, motorcycle.
Mock detector exists for tests when there's no model file around.
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

    # Cached security-class lookups: avoids per-frame list/np.array allocs.
    _SEC_IDS: tuple[int, ...] = tuple(SECURITY_CLASSES.keys())
    _SEC_IDS_ARR: np.ndarray = np.array(tuple(SECURITY_CLASSES.keys()), dtype=np.int32)

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

        if self._canvas is None or self._canvas.shape != (self._input_size, self._input_size, 3):
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

        sec_scores = class_scores[:, self._SEC_IDS]
        best_sec_local_idx = np.argmax(sec_scores, axis=1)
        best_sec_scores = np.max(sec_scores, axis=1)

        mask = best_sec_scores >= self._conf_threshold
        if not np.any(mask):
            return []

        valid_boxes = boxes[mask]
        valid_scores = best_sec_scores[mask]
        valid_class_ids = self._SEC_IDS_ARR[best_sec_local_idx[mask]]

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
        # Vectorised letterbox inversion + normalisation for all kept boxes:
        # one numpy pass replaces 4x np.clip + float ops per box in Python.
        # Math is identical to the scalar path (same op order), then only the
        # person sanity gates run per box (few survivors after NMS).
        keep_idx = np.asarray(indices, dtype=np.intp).ravel()
        kx1 = x1_lb[keep_idx]
        ky1 = y1_lb[keep_idx]
        kw = w[keep_idx]
        kh = h[keep_idx]
        # Same op order as the scalar path: ((v - pad) / scale) / dim.
        vx1 = np.clip((kx1 - pad_x) / scale / orig_w, 0.0, 1.0)
        vy1 = np.clip((ky1 - pad_y) / scale / orig_h, 0.0, 1.0)
        vx2 = np.clip((kx1 + kw - pad_x) / scale / orig_w, 0.0, 1.0)
        vy2 = np.clip((ky1 + kh - pad_y) / scale / orig_h, 0.0, 1.0)
        # Replicates the scalar x1/x2 swap for (theoretical) negative w/h.
        x_lo = np.minimum(vx1, vx2)
        x_hi = np.maximum(vx1, vx2)
        y_lo = np.minimum(vy1, vy2)
        y_hi = np.maximum(vy1, vy2)
        bw_all = x_hi - x_lo
        bh_all = y_hi - y_lo
        survivors = np.nonzero((bw_all > 0.005) & (bh_all > 0.005))[0]
        for k in survivors:
            kk = int(k)
            x1_norm = float(x_lo[kk])
            y1_norm = float(y_lo[kk])
            x2_norm = float(x_hi[kk])
            y2_norm = float(y_hi[kk])
            bw_norm = x2_norm - x1_norm
            bh_norm = y2_norm - y1_norm

            i = int(keep_idx[kk])
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
        # Fallback: if frame not empty, return centered person.
        # Mean is estimated on a strided (zero-copy) view: ~16x fewer pixels,
        # exact for uniform frames. Preserves the >5 threshold semantics.
        if float(np.mean(frame[::4, ::4])) > 5:
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
