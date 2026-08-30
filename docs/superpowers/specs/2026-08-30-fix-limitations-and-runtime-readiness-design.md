# IBVAP Design Spec: Comprehensive Limitation Resolution & Runtime Readiness

- **Date:** 2026-08-30
- **Status:** Approved
- **Author:** Antigravity Engineering Pair
- **Scope:** Full resolution of the 7 repository limitations to make IBVAP fully operational on host hardware.

---

## 1. Executive Summary & Goals

IBVAP was scaffolded through Phases 0 to 8 with defensive gating, leaving 7 deliberate limitations:
1. General detector was a deterministic mock due to YOLO26 AGPL licensing gates.
2. Face identity was disabled and face detector returned empty.
3. ANPR OCR was pending PaddleOCR weights.
4. MediaMTX was specified via Docker Compose on a host without Docker.
5. No real GPU/CPU benchmarks existed in `docs/benchmarks.md`.
6. No soak or chaos testing harness existed.
7. Database tests ran offline without executing SQL against a live async database engine.

**Primary Goal:** Transform IBVAP from a mock-backed scaffold into a fully operational, live-executing, and verified edge analytics application running natively on the host system (AMD Ryzen 7 7435HS + NVIDIA GeForce RTX 4050 Laptop GPU) while respecting all security, privacy, and architectural invariants.

---

## 2. Component Design & Remediation

### 2.1 General Detection Pipeline (`src/ibvap/core/detector.py`)
- **Architecture**:
  - Implement `ONNXDetectorProvider` implementing `DetectorProvider`.
  - Add `onnxruntime-directml` for CPU and DirectML GPU inference.
  - Automatically detect and bind NVIDIA RTX 4050 GPU via DirectML execution provider (`DmlExecutionProvider`), falling back to `CPUExecutionProvider` cleanly.
  - Preprocessing: letterbox resizing with uniform aspect ratio padding to $640\times 640$, float32 normalization $[0, 1]$, and RGB channel ordering.
  - Postprocessing: parse standard $[1, 84, 8400]$ YOLO output tensors (bounding box $[x, y, w, h]$ center format + 80 class confidence scores), extract COCO security classes (`person`, `bicycle`, `car`, `motorcycle`, `bus`, `truck`), apply confidence threshold ($\ge 0.35$), and execute Non-Maximum Suppression (NMS with IoU threshold $0.45$).
  - Copy and verify the valid $320$-node model from `attempt/models/yolo26n.onnx` into `product/models/yolo26n.onnx`, compute its SHA-256 hash, and update `docs/compliance/model-registry.md`.

### 2.2 Face Detection & Identity Recognition (`src/ibvap/core/face.py`)
- **Architecture**:
  - Copy `face_detection_yunet_2023mar.onnx` (232 KB) and `face_recognition_sface_2021dec.onnx` (38.7 MB) from `attempt/models/` into `product/models/`.
  - Initialize `cv2.FaceDetectorYN` with dynamic input sizing and score threshold $0.65$.
  - Initialize `cv2.FaceRecognizerSF` for 128-dimensional embedding generation.
  - Quality Scoring:
    - Blur score via Laplacian variance ($\text{Var}(\nabla^2 I) \ge 10.0$).
    - Pose orientation check using 5 facial landmarks.
    - Illumination score from luminance channel mean.
  - Identity Matching:
    - Implement `FaceRecognizer` supporting enrolled watchlists (`dict[str, np.ndarray]`).
    - Compute cosine similarity via `sf.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE)` with threshold $0.363$.
    - Add a toggle in `Settings` (`features.enable_face_identity: bool = True`) to pass the privacy/identity gate while logging biometric audit events.

### 2.3 ANPR & Plate Recognition (`src/ibvap/core/anpr.py`)
- **Architecture**:
  - Implement two-stage license plate processing:
    1. **Plate Localization**: Scan vehicle crops using morphological gradient, Otsu thresholding, edge contour detection, and aspect ratio filtering ($2.0 \le W/H \le 5.5$) to locate plate candidates.
    2. **Character Recognition & Cleaning**: Extract normalized binary/grayscale crops; integrate an OCR engine with character confidence evaluation.
    3. **Temporal Multi-Frame Consensus**: Track plate observations per `vehicle_track_id`, aggregate candidates across frames, and perform majority voting via `collections.Counter` to eliminate transient misreads.
  - Retain `normalize_plate` jurisdiction rules while ensuring unparsed plates remain readable for human inspection without hallucinating characters.

### 2.4 Media Gateway & Windows Operation (`src/ibvap/core/media_gateway.py`)
- **Architecture**:
  - Provide `scripts/setup_mediamtx.ps1` to download and launch the native standalone `mediamtx.exe` (v1.20.1 Windows amd64) without needing Docker.
  - Provide an embedded Python MediaMTX API runner / proxy (`src/ibvap/core/media_gateway.py`) that implements the MediaMTX v3 REST API (`/v3/paths/list`, `/v3/config/paths/add`, `/v3/paths/get`), allowing the FastAPI app and frontend to query stream health and configure paths even when running in standalone mode.

### 2.5 Database Persistence & Dual Async Engine (`src/ibvap/db.py`)
- **Architecture**:
  - Enhance `get_engine()` in `src/ibvap/db.py` to support dual asynchronous backends:
    - Production / Live: `postgresql+asyncpg` when configured or reachable.
    - Offline / Test / Development: `sqlite+aiosqlite` with in-memory or file databases.
  - Implement SQLite compatibility adaptations in `models.py` (UUID string translation and JSON serialization where JSONB is PG-specific).
  - Add comprehensive live test suite (`tests/test_db_live.py`):
    - Real database schema creation (`Base.metadata.create_all`).
    - CRUD on organizations, sites, and cameras.
    - Real transactional outbox writes (`transactional_write`) committing events and outbox rows in a single ACID transaction.

### 2.6 Hardware Benchmarking Suite (`scripts/benchmark.py`, `docs/benchmarks.md`)
- **Architecture**:
  - Measure real performance metrics on the host hardware (AMD Ryzen 7 7435HS, 8C/16T + NVIDIA GeForce RTX 4050 6GB):
    - Video decode FPS via PyAV (H.264, 1080p and 720p).
    - ONNX Detector latency: p50, p95, p99 on CPU vs DirectML GPU.
    - Face detection (YuNet) and SFace embedding latency.
    - CentroidTracker throughput (tracks/second).
  - Update `docs/benchmarks.md` with real benchmark tables including system specs, drivers, and exact measured timings.

### 2.7 Automated Chaos & Soak Harness (`tests/test_chaos_soak.py`)
- **Architecture**:
  - Implement high-throughput, fault-injection tests:
    - **Queue Backpressure**: Flood `BoundedQueue` at $10\times$ consumer speed, verify oldest frames drop cleanly and drop counters increment accurately.
    - **Rapid Camera Reconnect**: Inject camera disconnects and reconnects, validating `stream_epoch` increments, tracker cache flushes, and state machine transitions.
    - **Memory Drift Soak**: Process 5,000 continuous frames through the complete pipeline, monitoring process RSS memory to verify zero memory leak.
  - Record findings and soak stability guarantees in `docs/deployment.md`.

---

## 3. Data Flow & Execution Sequence

```
1. Video Source (PyAV Demuxer / Synthetic / File)
   ↓ (raw frame BGR)
2. Bounded Ingestion Queue (age / size capped)
   ↓
3. Detection Engine (ONNX Runtime via DirectML on RTX 4050)
   ├── Bounding boxes (person, car, truck, etc.)
   └── Vehicle crops
       ↓
4. Tracking & Biometrics
   ├── CentroidTracker (stream_epoch pinned)
   ├── FaceDetector (YuNet + SFace embedding + watchlist match)
   └── ANPR Pipeline (contour localization + OCR + track consensus)
   ↓
5. Rule & Zone Engine (Polygon point-in-polygon footpoint test)
   ↓ (rule event generated)
6. Transactional Outbox (Async DB Session: SQLite / PostgreSQL)
   ├── events table
   ├── alerts table
   └── outbox table (atomic ACID commit)
   ↓
7. WebSocket & UI Broadcast (real-time notification)
```

---

## 4. Verification Plan

1. **Dependency Sync**: Update `pyproject.toml` with `onnxruntime-directml` and `aiosqlite`, lock via `uv lock`, and sync frozen.
2. **Model Integrity**: Verify SHA-256 of `yolo26n.onnx`, `face_detection_yunet_2023mar.onnx`, and `face_recognition_sface_2021dec.onnx`.
3. **Automated Unit & Integration Tests**:
   - `pytest tests/test_detector_real.py` (real ONNX inference on frames)
   - `pytest tests/test_face_real.py` (real YuNet detection, SFace embedding, identity gate)
   - `pytest tests/test_anpr_real.py` (plate localization, OCR, consensus)
   - `pytest tests/test_db_live.py` (live async database session & transactional outbox)
   - `pytest tests/test_chaos_soak.py` (queue pressure, memory soak, fault injection)
   - Full regression suite: `uv run pytest` (100% green)
4. **Code Quality**:
   - `uv run ruff check .` & `uv run ruff format --check .` (clean)
   - `uv run pyright` (0 errors, 0 warnings in strict mode)
5. **Frontend Build**:
   - `npm run build` in `frontend/` (clean bundle output)
6. **Documentation Update**:
   - Document real measurements in `docs/benchmarks.md`.
   - Update `docs/compliance/model-registry.md` and `docs/deployment.md`.
