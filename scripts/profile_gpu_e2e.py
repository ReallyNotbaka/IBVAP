"""Profiling script for IBVAP GPU optimization investigation.

Measures exact millisecond breakdowns on real video footage (data/test_upload_face.mp4):
- Decoding latency (PyAV)
- Detector preprocessing latency
- Detector ONNX inference latency (DirectML vs CPU)
- Detector postprocessing & NMS latency
- YuNet face detection latency
- SFace alignment and embedding extraction latency
- JPEG encoding latency
- End-to-end pipeline latency and FPS
"""

from __future__ import annotations

import time
from pathlib import Path
import av
import cv2
import numpy as np
import onnxruntime as ort

from ibvap.core.detector import ONNXDetectorProvider, SECURITY_CLASSES
from ibvap.core.face import FaceDetector, FaceRecognizer
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.tracker import CentroidTracker


def profile_real_video(video_path: str = "data/test_upload_face.mp4", loops: int = 5, max_frames: int = 50):
    print(f"=== Profiling Real Video: {video_path} ({loops} passes) ===")
    p = Path(video_path)
    if not p.exists():
        print(f"File not found: {video_path}")
        return

    # 1. PyAV decoding latency
    decode_times = []
    frames = []
    container = av.open(str(p))
    stream = next((s for s in container.streams if s.type == "video"), None)
    for frame in container.decode(stream):
        t0 = time.perf_counter()
        img = frame.to_ndarray(format="bgr24")
        t1 = time.perf_counter()
        decode_times.append((t1 - t0) * 1000.0)
        frames.append(img)
        if len(frames) >= max_frames:
            break
    container.close()

    print(f"Decoded {len(frames)} frames. PyAV decode to_ndarray: mean={np.mean(decode_times):.2f}ms, min={np.min(decode_times):.2f}ms, max={np.max(decode_times):.2f}ms")

    # 2. JPEG encoding latency
    jpeg_times = []
    for img in frames:
        h, w = img.shape[:2]
        preview = cv2.resize(img, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_LINEAR) if w > 1280 else img
        t0 = time.perf_counter()
        ok, enc = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
        t1 = time.perf_counter()
        if ok:
            jpeg_times.append((t1 - t0) * 1000.0)
    print(f"JPEG encode (quality 65): mean={np.mean(jpeg_times):.2f}ms, min={np.min(jpeg_times):.2f}ms, max={np.max(jpeg_times):.2f}ms")

    # 3. ONNX Detector Breakdown
    detector = ONNXDetectorProvider("models/yolo26n.onnx")
    print(f"ONNX Detector initialized. Active runtime: {detector.runtime}")

    preprocess_times = []
    infer_times = []
    postprocess_times = []
    nms_times = []
    total_det_times = []

    # Warmup
    for img in frames[:3]:
        detector.detect(img)

    for _ in range(loops):
        for img in frames:
            t_start = time.perf_counter()
            # Stage A: Preprocess
            t0 = time.perf_counter()
            blob, scale, pad_x, pad_y = detector._preprocess(img)
            t1 = time.perf_counter()
            preprocess_times.append((t1 - t0) * 1000.0)

            # Stage B: Inference
            t0 = time.perf_counter()
            outputs = detector._session.run(None, {detector._input_name: blob})
            t1 = time.perf_counter()
            infer_times.append((t1 - t0) * 1000.0)

            # Stage C: Postprocessing before NMS
            t0 = time.perf_counter()
            output = np.asarray(outputs[0], dtype=np.float32)
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
            mask = best_sec_scores >= detector._conf_threshold

            valid_boxes = boxes[mask]
            valid_scores = best_sec_scores[mask]
            valid_class_ids = np.array(sec_class_ids, dtype=np.int32)[best_sec_local_idx[mask]]

            cx = valid_boxes[:, 0]
            cy = valid_boxes[:, 1]
            w = valid_boxes[:, 2]
            h = valid_boxes[:, 3]
            x1_lb = cx - w / 2.0
            y1_lb = cy - h / 2.0

            class_offsets = (valid_class_ids * 10000.0).astype(np.float32)
            boxes_for_nms = np.column_stack((x1_lb + class_offsets, y1_lb, w, h))
            t1 = time.perf_counter()
            postprocess_times.append((t1 - t0) * 1000.0)

            # Stage D: NMS
            t0 = time.perf_counter()
            indices = cv2.dnn.NMSBoxes(boxes_for_nms, valid_scores, detector._conf_threshold, detector._iou_threshold)
            t1 = time.perf_counter()
            nms_times.append((t1 - t0) * 1000.0)

            total_det_times.append((time.perf_counter() - t_start) * 1000.0)

    print("\n--- Detector Timing Breakdown (Per Frame) ---")
    print(f"Preprocessing:        mean={np.mean(preprocess_times):.2f}ms (p50={np.median(preprocess_times):.2f}ms, p95={np.percentile(preprocess_times, 95):.2f}ms)")
    print(f"Inference:            mean={np.mean(infer_times):.2f}ms (p50={np.median(infer_times):.2f}ms, p95={np.percentile(infer_times, 95):.2f}ms)")
    print(f"Postprocessing:       mean={np.mean(postprocess_times):.2f}ms (p50={np.median(postprocess_times):.2f}ms, p95={np.percentile(postprocess_times, 95):.2f}ms)")
    print(f"NMS (cv2.dnn):        mean={np.mean(nms_times):.2f}ms (p50={np.median(nms_times):.2f}ms, p95={np.percentile(nms_times, 95):.2f}ms)")
    print(f"Total Detect Call:    mean={np.mean(total_det_times):.2f}ms (p50={np.median(total_det_times):.2f}ms, p95={np.percentile(total_det_times, 95):.2f}ms)")
    print(f"Detector Standalone FPS: {1000.0 / np.mean(total_det_times):.1f} FPS")

    # 4. Face Detection (YuNet) and Recognition (SFace) Timing
    yunet = FaceDetector()
    yunet_times = []
    if yunet._detector is not None:
        for img in frames[:3]:
            yunet.detect(img)
        for _ in range(loops):
            for img in frames:
                t0 = time.perf_counter()
                f_res = yunet.detect(img)
                t1 = time.perf_counter()
                yunet_times.append((t1 - t0) * 1000.0)
        print(f"\nYuNet Face Detect:    mean={np.mean(yunet_times):.2f}ms (p50={np.median(yunet_times):.2f}ms, p95={np.percentile(yunet_times, 95):.2f}ms)")

    sface = FaceRecognizer()
    sface_times = []
    if sface._recognizer is not None:
        real_crop = np.random.randint(50, 200, (112, 112, 3), dtype=np.uint8)
        for _ in range(3):
            sface.extract_feature(real_crop)
        for _ in range(loops * 10):
            t0 = time.perf_counter()
            _ = sface.extract_feature(real_crop)
            t1 = time.perf_counter()
            sface_times.append((t1 - t0) * 1000.0)
        print(f"SFace Feature Extract: mean={np.mean(sface_times):.2f}ms (p50={np.median(sface_times):.2f}ms, p95={np.percentile(sface_times, 95):.2f}ms)")

    # 5. MiniPipeline End-to-End Timing
    pipeline = MiniPipeline(
        camera_id="profile-cam",
        detector=detector,
        enable_face=True,
        face_stride=2,
        sample_stride=1,
    )
    # Warmup
    for img in frames[:3]:
        pipeline.process_frame(img)

    pipe_times = []
    for _ in range(loops):
        for img in frames:
            t0 = time.perf_counter()
            pipeline.process_frame(img)
            t1 = time.perf_counter()
            pipe_times.append((t1 - t0) * 1000.0)

    print("\n--- End-to-End Pipeline Timing (Per Frame) ---")
    print(f"Pipeline process_frame: mean={np.mean(pipe_times):.2f}ms (p50={np.median(pipe_times):.2f}ms, p95={np.percentile(pipe_times, 95):.2f}ms)")
    print(f"End-to-End Pipeline FPS: {1000.0 / np.mean(pipe_times):.1f} FPS")


if __name__ == "__main__":
    profile_real_video()
