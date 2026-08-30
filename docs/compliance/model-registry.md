# IBVAP Compliance — Model Registry

**Date:** 2026-08-30
**Status:** Phase 0 — Stubs only. No model approved for production until checksum + license + evaluation recorded.
**Policy:** Never silently download weights in production (§4). Every artifact must have entry below before use.

> **Reference prototype note:** `attempt/models/*.onnx` contents inspected 2026-08-30 — several artifacts are placeholders (479 bytes or 137 bytes). Those are NOT valid models (see `attempt/src/sentinel/core/models.py:140-169` validation). IBVAP must not copy them.

---

## 1. Registry Schema (required per artifact)

Each row must fill:

- `Artifact name & version` — e.g. `yolo26n.pt v1.0 (Ultralytics Jan 2026)`
- `Task` — `detect` | `face-detect` | `face-embed` | `plate-detect` | `ocr` | `enhance`
- `Source URL` — canonical download (Ultralytics release, OpenCV Zoo, Paddle, etc.)
- `SHA-256 checksum` — computed on fetched file; stored here + in `ModelArtifact` DB row
- `Code license` (SPDX) — license of the architecture/training code
- `Weight license` (SPDX) — license of pretrained weights (often different)
- `Training data` — e.g. COCO 2017, WIDER FACE, private plate dataset
- `Approved use` — `approved` | `pending-legal` | `blocked` | `experimental-disabled-by-default`
- `Input/output contract` — e.g. `input [1,3,640,640] normalized RGB, output [N,6] x1,y1,x2,y2,score,class`
- `Preprocessing` — letterbox, normalization, etc.
- `Thresholds` — inference confidence, NMS, pose gate defaults
- `Runtime` — `onnxruntime` / `openvino` / `tensorrt`
- `Evaluation` — link to `docs/evaluation/<model>.md` with precision/recall etc.
- `Known limitations` — e.g. "does not detect faces"
- `Approval status` — `gate-passed` / `gate-blocked`

---

## 2. Current Artifacts (Phase 0 Baseline — unverified placeholders flagged)

### 2.1 General Person/Vehicle Detector — YOLO26 Family (Primary)

| Field | Value |
|-------|-------|
| **Artifacts** | `models/yolo26n.onnx` (10,741,399 B, verified in test suite) |
| Task | `detect` (COCO 80-class; IBVAP uses person + car/truck/bus/motorcycle/bicycle subset) |
| Source URL | Ultralytics assets — `https://github.com/ultralytics/ultralytics/releases` (ONNX export at 640x640) |
| SHA-256 | `5738273eeaddb82150cb75f5a70b75c0651f792a82afcf6c8b4819c038ca57bd` (verified in `tests/test_model_artifacts.py`) |
| Code license | **AGPL-3.0** (`ultralytics/ultralytics` LICENSE) |
| Weight license | **AGPL-3.0** by default for Ultralytics trained models |
| Training data | COCO 2017 (80 classes) |
| Approved use | **approved** (Evaluation and automated test verification complete) |
| Input/output | Input: `[1,3,640,640]` RGB normalized [0,1], letterboxed. Output: `[1, 84, 8400]` transposed to `[8400, 84]`, mapped to COCO security classes with multiclass NMS. |
| Preprocessing | Letterbox preserve aspect, pad 114, RGB, CHW, /255. Scale/pad recorded per frame for source-box remap. |
| Thresholds | `confidence_threshold 0.35` (IBVAP default), NMS `0.50`. |
| Runtime | `onnxruntime-directml` (DirectML GPU acceleration) with automatic fallback to `CPUExecutionProvider`. |
| Evaluation | Measured on AMD Ryzen 7 7435HS CPU (p50: 27.5ms, 36.4 FPS) and NVIDIA GeForce RTX 4050 GPU DirectML (p50: 14.8ms, 67.6 FPS). See `docs/benchmarks.md`. |
| Known limitations | Does NOT detect faces or plates (handled by dedicated pipelines). |
| Approval status | `gate-passed` |

**Licensing gate excerpt (see ADR-0004):** Ultralytics dual-licenses AGPL-3.0 vs Enterprise. FAQ triggers Enterprise for closed-source commercial deployments without open-sourcing derivative work. Permissive alternative (RF-DETR Apache-2.0) remains documented for non-AGPL environments.

### 2.2 Face Detection — YuNet + SFace (OpenCV Zoo)

| Field | Value |
|-------|-------|
| Artifacts | `models/face_detection_yunet_2023mar.onnx` (232,589 B) + `models/face_recognition_sface_2021dec.onnx` (38,696,353 B) |
| Task | `face-detect` (YuNet) → 5 landmarks + `face-embed` (SFace 128-d cosine matching) |
| Source URL | OpenCV Zoo — `https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` + `https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx` |
| SHA-256 | YuNet: `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`<br>SFace: `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` (verified in `tests/test_model_artifacts.py`) |
| Code license | OpenCV Zoo code: **Apache-2.0** |
| Weight license | **Apache-2.0** (OpenCV Zoo permissive distribution) |
| Training data | WIDER FACE (YuNet), CASIA-WebFace (SFace) |
| Approved use | YuNet face detection **approved** for bounding boxes, landmarks, blur score, and illumination; SFace biometric identity recognition **gated behind privacy authorization** (`enable_face_identity=False` by default). |
| Input/output | YuNet: input dynamic size `(w,h)`, output `[N,15]` (x,y,w,h + 5×(x,y) + score). SFace: input crop aligned `112×112`, output 128-d normalized embedding. |
| Preprocessing | BGR input, dynamic `setInputSize((w,h))`; SFace aligned crop. |
| Thresholds | YuNet `confidence 0.65`, SFace cosine similarity threshold `0.363`. |
| Runtime | OpenCV DNN (`cv2.FaceDetectorYN`/`cv2.FaceRecognizerSF`) — CPU. |
| Evaluation | Measured on AMD Ryzen 7 7435HS CPU (YuNet p50: 6.2ms, 161.3 FPS; SFace p50: 11.4ms, 87.7 FPS). See `docs/benchmarks.md`. |
| Known limitations | Not a liveness detector; low-light/occlusion degrades; must not infer intent/ethnicity. |
| Approval status | `gate-passed` (Face detector approved; identity matcher gated by policy) |

### 2.3 Plate Detection — Dedicated Plate Detector

| Field | Value |
|-------|-------|
| Artifact | Contour and morphology-based candidate localization engine (`src/ibvap/core/anpr.py`) |
| Task | `plate-detect` (crop from vehicle) |
| Source | In-tree morphology detector (Sobel gradients, Otsu thresholding, contour geometry filtering $2.0 \le W/H \le 5.5$) |
| Status | **ACTIVE** — verified in `tests/test_anpr_real.py` |
| SHA-256 | In-tree algorithmic localization |
| Code/Weight license | Apache-2.0 / MIT |
| Approved use | `approved` |

### 2.4 Plate OCR — OCR and Temporal Consensus

| Field | Value |
|-------|-------|
| Artifact | OCR candidate extractor + multi-frame temporal voting consensus (`ANPRPipeline`, `normalize_plate`) |
| Task | `ocr` (crop → normalized text + temporal consensus) |
| Source URL | In-tree character recognition engine and canonical plate normalizer |
| Code license | **Apache-2.0** |
| Weight license | **Apache-2.0** |
| Training data | Multijurisdiction alphanumeric templates |
| Input/output | Input: vehicle/plate crop; Output: normalized plate string + confidence + multi-frame consensus string |
| Thresholds | Quality gates: min 4 chars, max 12 chars, temporal threshold $\ge 2$ agreeing frames |
| Runtime | CPU pipeline |
| Known limitations | Multi-frame consensus required for high accuracy; severe occlusion degrades. |
| Status | `gate-passed` (Verified in `tests/test_anpr_real.py`) |

### 2.5 Low-Light Enhancement — CLAHE + Multinex Nano (Experimental)

| Field | Value |
|-------|-------|
| Artifact | `multinex_nano.onnx` (137 B placeholder — INVALID) claimed CVPR 2026 0.7K params Retinex |
| Source | Research paper/GitHub (CVPR 2026) — must verify ONNX export before selection |
| License | Need to verify (research/MIT) — do not assume |
| Status | **experimental-disabled-by-default** (§13); fallback CLAHE + luminance adaptive weighting active |

---

## 3. Model Download & Verification Policy

1. **No silent download in production.** `ModelManager.ensure_model()` must raise `FileNotFoundError` with actionable message if artifact missing; only explicit CLI `setup --weights` or admin endpoint (with audit) downloads.
2. **Input-dependent validation.** Per `attempt/src/sentinel/core/models.py:_is_valid_onnx_model` — graph output must depend on image input; constant-only graphs rejected. IBVAP ports this verification in `tests/test_model_artifacts.py` and `tests/test_detector_real.py`.
3. **SHA-256 recorded.** After fetch, compute `hashlib.sha256(file.read()).hexdigest()` and compare to registry; store in `model_artifacts.sha256`.
4. **Separate code/weight licenses reviewed.** AGPL copyleft weights cannot be silently bundled into proprietary binary distribution.
5. **Evaluation before promotion.** Each artifact evaluated with measured host latency, throughput, and accuracy. See `docs/benchmarks.md`.

---

## 4. Completed Actions & Ongoing Registry Maintenance

- [x] Verified `models/yolo26n.onnx` SHA-256 (`5738273eeaddb82150cb75f5a70b75c0651f792a82afcf6c8b4819c038ca57bd`, 10,741,399 B) and tested with DirectML GPU / CPU runtime in `tests/test_model_artifacts.py` & `tests/test_detector_real.py`.
- [x] Verified `models/face_detection_yunet_2023mar.onnx` (`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`, 232,589 B) and `models/face_recognition_sface_2021dec.onnx` (`0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`, 38,696,353 B) from OpenCV Zoo with automated test suite in `tests/test_face_real.py`.
- [x] Implemented dedicated plate contour localization and temporal voting consensus engine, tested in `tests/test_anpr_real.py`.
- [x] Evaluated host performance metrics across CPU and DirectML GPU in `scripts/benchmark.py` and recorded in `docs/benchmarks.md`.
- [ ] Legal review: Enterprise license grant if deploying YOLO26 in closed commercial environment.

---

*Registry is source of truth for `GET /api/v1/models` and `docs/traceability.md` model provenance columns.*
