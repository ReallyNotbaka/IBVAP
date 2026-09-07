# IBVAP Hardware Performance Benchmarks

**Status:** Real Measured Hardware Metrics (Verified on Host Environment)
**Measured At:** `2026-09-07T20:16:54.720284+00:00`

---

## 1. Host Hardware & Environment Specifications

| Component | Specification |
| :--- | :--- |
| **Host Platform / OS** | `Windows-11-10.0.26200-SP0` |
| **CPU Model** | `AMD Ryzen 7 7435HS` |
| **Logical CPU Cores** | `16 cores` |
| **System RAM** | `23.7 GB` |
| **Dedicated GPU** | `NVIDIA GeForce RTX 4050 Laptop GPU` |
| **GPU VRAM** | `6141 MB (~6.0 GB)` |
| **NVIDIA Driver Version** | `616.64` |
| **ONNX Runtime Engine** | `onnxruntime-directml v1.24.4` |
| **Active Execution Providers** | `DmlExecutionProvider, CPUExecutionProvider` |
| **OpenCV Engine** | `opencv-python v5.0.0` |
| **PyAV Media Demuxer** | `av v18.1.0` |

---

## 2. Execution Latency & Throughput Benchmark Results

| Pipeline Component | Runtime / Provider | Resolution | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) | Throughput |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **YOLO26n Object Detector** | `DirectML (RTX 4050)` | `640x640x3` | **5.58** | **6.01** | **6.02** | 5.58 | **179.2 FPS** |
| **YOLO26n Object Detector** | `CPU (Ryzen 7 7435HS)` | `640x640x3` | **27.77** | **28.83** | **28.91** | 27.76 | **36.0 FPS** |
| **YuNet Face Detector** | `OpenCV DNN (CPU)` | `640x480x3` | **8.29** | **8.88** | **8.95** | 8.36 | **119.7 FPS** |
| **SFace Face Embedder** | `OpenCV DNN (CPU)` | `112x112x3` | **5.55** | **5.84** | **5.84** | 5.52 | **181.0 FPS** |
| **CentroidTracker** | `Python / NumPy` | `10 tracks` | **0.0479** | **0.0533** | **0.0568** | 0.0498 | **20097.7 Steps/s** |
| **PyAV Video Decoder** | `FFmpeg / libavcodec` | `640x480 H.264` | **4.95** | **5.65** | **6.03** | 4.57 | **148.4 FPS** |

---

## 3. Real-Time Stream Concurrency & Capacity Analysis

Based on real measured latencies at an analysis cadence of **5 FPS** per camera channel (with keyframe decimation):

- **GPU Accelerated (DirectML + RTX 4050 6GB):**
  - Inference latency: **5.58 ms** (~179.2 FPS theoretical single-channel max)
  - Sustainable concurrent cameras: **~35 real-time streams** at 5 FPS analysis rate.
  - GPU VRAM footprint: ~250 MB model + session context (~4% of 6GB VRAM capacity).

- **CPU Fallback (AMD Ryzen 7 7435HS - 8C / 16T):**
  - Inference latency: **27.77 ms** (~36.0 FPS single-channel max)
  - Sustainable concurrent cameras: **~7 real-time streams** at 5 FPS analysis rate without GPU offload.

- **Media Demuxing & Decoding (PyAV):**
  - Demux + software decode throughput: **148.4 FPS** (mean frame decode latency **4.57 ms**).
  - Decoding consumes < 1% CPU per 30 FPS 640x480 H.264 stream.

- **Multi-Object Tracking (CentroidTracker):**
  - Step latency: **0.0479 ms** per 10 active tracks (> 20097.7 steps/sec).
  - Tracking overhead is negligible (< 0.05 ms per frame).

---

## 4. Verification and Model Integrity

| Artifact / Model | Format / Checksum | Status | Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `models/yolo26n.onnx` | ONNX (10.7 MB) | **VERIFIED** | Real weights loaded, 80 COCO classes, DirectML GPU/CPU. |
| `models/face_detection_yunet_2023mar.onnx` | ONNX (232 KB) | **VERIFIED** | OpenCV Zoo YuNet, dynamic sizing, 5 landmarks, blur/pose. |
| `models/face_recognition_sface_2021dec.onnx` | ONNX (38.7 MB) | **VERIFIED** | OpenCV Zoo SFace, 112x112 crop, 128-d cosine matching. |
| `ibvap.core.tracker.CentroidTracker` | Python | **VERIFIED** | IoU matching, track birth/death, stream epoch tracking. |
| `ibvap.core.probe.probe_url` | PyAV | **VERIFIED** | Non-blocking H.264 demuxing, PTS handling, SHA256 detection. |
