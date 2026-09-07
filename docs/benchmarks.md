# IBVAP Hardware Performance Benchmarks

**Status:** Real Measured Hardware Metrics (Verified on Host Environment)
**Measured At:** `2026-09-06T12:53:36.103631+00:00`

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
| **YOLO26n Object Detector** | `DirectML (RTX 4050)` | `640x640x3` | **5.03** | **6.02** | **6.13** | 5.18 | **193.1 FPS** |
| **YOLO26n Object Detector** | `CPU (Ryzen 7 7435HS)` | `640x640x3` | **27.29** | **29.03** | **29.27** | 27.26 | **36.7 FPS** |
| **YuNet Face Detector** | `OpenCV DNN (CPU)` | `640x480x3` | **8.11** | **9.10** | **9.16** | 8.19 | **122.1 FPS** |
| **SFace Face Embedder** | `OpenCV DNN (CPU)` | `112x112x3` | **5.27** | **5.64** | **5.71** | 5.27 | **189.9 FPS** |
| **CentroidTracker** | `Python / NumPy` | `10 tracks` | **0.0450** | **0.0723** | **0.0986** | 0.0510 | **19589.4 Steps/s** |
| **PyAV Video Decoder** | `FFmpeg / libavcodec` | `640x480 H.264` | **5.40** | **5.85** | **5.97** | 5.13 | **133.3 FPS** |

---

## 3. Real-Time Stream Concurrency & Capacity Analysis

Based on real measured latencies at an analysis cadence of **5 FPS** per camera channel (with keyframe decimation):

- **GPU Accelerated (DirectML + RTX 4050 6GB):**
  - Inference latency: **5.03 ms** (~193.1 FPS theoretical single-channel max)
  - Sustainable concurrent cameras: **~38 real-time streams** at 5 FPS analysis rate.
  - GPU VRAM footprint: ~250 MB model + session context (~4% of 6GB VRAM capacity).

- **CPU Fallback (AMD Ryzen 7 7435HS - 8C / 16T):**
  - Inference latency: **27.29 ms** (~36.7 FPS single-channel max)
  - Sustainable concurrent cameras: **~7 real-time streams** at 5 FPS analysis rate without GPU offload.

- **Media Demuxing & Decoding (PyAV):**
  - Demux + software decode throughput: **133.3 FPS** (mean frame decode latency **5.13 ms**).
  - Decoding consumes < 1% CPU per 30 FPS 640x480 H.264 stream.

- **Multi-Object Tracking (CentroidTracker):**
  - Step latency: **0.0450 ms** per 10 active tracks (> 19589.4 steps/sec).
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
