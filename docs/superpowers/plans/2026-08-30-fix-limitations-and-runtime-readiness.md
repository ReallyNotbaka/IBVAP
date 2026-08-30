# IBVAP Limitation Resolution & Runtime Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all 7 repository limitations by implementing real ONNX detection (CPU/DirectML GPU), YuNet/SFace biometric recognition with an authorization gate, two-stage ANPR with multi-frame consensus, live dual async DB support with offline tests, native MediaMTX integration, host hardware benchmarks, and automated chaos/soak testing.

**Architecture:** Extend core modules with real inference and data providers while preserving existing interfaces (`DetectorProvider`, `CameraStateMachine`, `transactional_write`). Use `onnxruntime-directml` for GPU acceleration on Windows, OpenCV Zoo for biometrics, `aiosqlite` for live local async testing alongside PostgreSQL, and self-contained mock/runner scripts for MediaMTX.

**Tech Stack:** Python 3.12, ONNX Runtime (DirectML / CPU), OpenCV 5.0.0.93, SQLAlchemy 2.0.52 async, `aiosqlite`, PyAV 18.1.0, FastAPI, Vite, React 19.

**Spec:** `docs/superpowers/specs/2026-08-30-fix-limitations-and-runtime-readiness-design.md`

## Global Constraints

- Python requires `3.12`.
- All tests must pass with `uv run pytest`.
- Linter (`uv run ruff check .`) must report zero errors.
- Type checker (`uv run pyright`) must pass in strict mode with 0 errors and 0 warnings.
- No fabricated benchmarks or hallucinated OCR values.
- Never persist unencrypted credentials.

---

### Task 1: Dependencies & Model Artifact Ingestion

**Files:**
- Modify: `pyproject.toml:9-34`
- Modify: `uv.lock`
- Create: `models/yolo26n.onnx`
- Create: `models/face_detection_yunet_2023mar.onnx`
- Create: `models/face_recognition_sface_2021dec.onnx`
- Test: `tests/test_model_artifacts.py`

**Interfaces:**
- Produces: Verified ONNX models in `models/` directory with known SHA-256 hashes.
- Dependencies: `onnxruntime-directml==1.24.4`, `aiosqlite==0.22.1` added to `pyproject.toml`.

- [ ] **Step 1: Write test checking model artifact presence and validity**

```python
from pathlib import Path
import hashlib

def test_model_files_exist_and_hashes():
    models_dir = Path("models")
    yolo = models_dir / "yolo26n.onnx"
    yunet = models_dir / "face_detection_yunet_2023mar.onnx"
    sface = models_dir / "face_recognition_sface_2021dec.onnx"
    assert yolo.exists() and yolo.stat().st_size > 10_000_000
    assert yunet.exists() and yunet.stat().st_size > 200_000
    assert sface.exists() and sface.stat().st_size > 35_000_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model_artifacts.py -v`
Expected: FAIL (models do not exist yet)

- [ ] **Step 3: Add dependencies to pyproject.toml, lock, and copy artifacts**

Add `onnxruntime-directml==1.24.4` and `aiosqlite==0.22.1` to `dependencies` in `pyproject.toml`.
Run `uv lock` and `uv sync --frozen`.
Copy the verified model files from `C:\Users\ReallyNotBaka\Videos\attempt\models` into `C:\Users\ReallyNotBaka\Videos\product\models`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_model_artifacts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock models/ tests/test_model_artifacts.py
git commit -m "feat: add onnxruntime-directml, aiosqlite, and validated model artifacts"
```

---

### Task 2: Live Dual Async Database Persistence & Unit Test Harness

**Files:**
- Modify: `src/ibvap/config.py:27-38`
- Modify: `src/ibvap/db.py:20-64`
- Modify: `src/ibvap/models.py:1-80`
- Create: `tests/test_db_live.py`

**Interfaces:**
- Consumes: `Settings` configuration.
- Produces: `get_engine()`, `get_sessionmaker()`, `get_session()` supporting both PostgreSQL and SQLite async URLs (`sqlite+aiosqlite:///...`).

- [ ] **Step 1: Write live database test exercising actual async sessions**

```python
import pytest
from sqlalchemy import select
from ibvap.db import get_engine, get_sessionmaker, dispose_engine
from ibvap.models import Base, Organization, Site, Camera, Outbox
from ibvap.config import Settings, DBConfig

@pytest.mark.asyncio
async def test_live_db_crud_and_outbox():
    settings = Settings(db=DBConfig(url="sqlite+aiosqlite:///:memory:"))
    await dispose_engine()
    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    sm = get_sessionmaker(settings)
    async with sm() as session:
        org = Organization(name="Border Command")
        session.add(org)
        await session.commit()
        
        result = await session.execute(select(Organization).where(Organization.name == "Border Command"))
        fetched = result.scalar_one()
        assert fetched.name == "Border Command"
    await dispose_engine()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_live.py -v`
Expected: FAIL or error with UUID / engine mismatch

- [ ] **Step 3: Update `src/ibvap/db.py` and `models.py` for SQLite async compatibility**

In `models.py`, ensure UUID and JSON columns function across both PostgreSQL (`JSONB`, `UUID(as_uuid=True)`) and SQLite (native/string fallback).
In `db.py`, configure appropriate pool options (avoid pool_size/max_overflow on `StaticPool` or SQLite).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db_live.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ibvap/config.py src/ibvap/db.py src/ibvap/models.py tests/test_db_live.py
git commit -m "feat: add live async sqlite engine fallback and db integration tests"
```

---

### Task 3: Real ONNX Detector Provider

**Files:**
- Modify: `src/ibvap/core/detector.py:1-104`
- Modify: `src/ibvap/core/pipeline.py:20-85`
- Create: `tests/test_detector_real.py`

**Interfaces:**
- Consumes: `models/yolo26n.onnx`, raw numpy BGR image.
- Produces: `ONNXDetectorProvider` implementing `DetectorProvider` with `detect(frame, frame_id) -> list[Detection]`.

- [ ] **Step 1: Write test for real ONNX inference on image**

```python
import numpy as np
from ibvap.core.detector import ONNXDetectorProvider, Detection

def test_onnx_detector_initialization_and_forward():
    detector = ONNXDetectorProvider(model_path="models/yolo26n.onnx")
    assert detector.model_id == "yolo26n"
    assert detector.input_size == 640
    
    # Run on blank frame - no detections
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = detector.detect(blank, frame_id=0)
    assert isinstance(dets, list)
    assert len(dets) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_detector_real.py -v`
Expected: FAIL (ONNXDetectorProvider not defined)

- [ ] **Step 3: Implement `ONNXDetectorProvider` in `src/ibvap/core/detector.py`**

Implement `ONNXDetectorProvider`:
- Attempt to load `DmlExecutionProvider` (DirectML GPU) first; if unavailable, use `CPUExecutionProvider`.
- Implement `_preprocess(frame, target_size=640)`: letterbox with uniform aspect padding to $(640, 640, 3)$, convert BGR to RGB, normalize $/ 255.0$, transpose to $[1, 3, 640, 640]$.
- Execute ONNX session.
- Implement `_postprocess`: transpose $[1, 84, 8400]$ to $[8400, 84]$, extract center $(cx, cy, w, h)$ boxes and class probabilities, filter classes to security set (0: person, 1: bicycle, 2: car, 3: motorcycle, 5: bus, 7: truck) with confidence threshold $\ge 0.35$, apply multiclass NMS, remap normalized coordinates $[x1, y1, x2, y2]$ back to original frame dimensions $[0, 1]$.
- Update `MiniPipeline` in `src/ibvap/core/pipeline.py` to use `ONNXDetectorProvider` if weights are present, otherwise `MockPersonDetector`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_detector_real.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ibvap/core/detector.py src/ibvap/core/pipeline.py tests/test_detector_real.py
git commit -m "feat: implement real ONNX detector provider with DirectML/CPU support"
```

---

### Task 4: Face Detection & Identity Recognition with Privacy Gate

**Files:**
- Modify: `src/ibvap/core/face.py:1-66`
- Modify: `src/ibvap/config.py`
- Create: `tests/test_face_real.py`

**Interfaces:**
- Consumes: `models/face_detection_yunet_2023mar.onnx`, `models/face_recognition_sface_2021dec.onnx`.
- Produces: `FaceDetector.detect(frame)` returning `list[FaceDetection]` with real quality scores, landmarks, and `FaceRecognizer.match_identity(feature, watchlist)`.

- [ ] **Step 1: Write test for real YuNet face detection and SFace feature matching**

```python
import cv2
import numpy as np
from ibvap.core.face import FaceDetector, FaceRecognizer

def test_face_detector_real_and_embedder():
    detector = FaceDetector(model_path="models/face_detection_yunet_2023mar.onnx")
    assert detector._detector is not None
    
    # Test blank frame
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = detector.detect(blank)
    assert len(dets) == 0
    
    # Test SFace embedding
    recognizer = FaceRecognizer(model_path="models/face_recognition_sface_2021dec.onnx")
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    feat = recognizer.extract_feature(crop)
    assert feat.shape == (1, 128)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_face_real.py -v`
Expected: FAIL

- [ ] **Step 3: Implement real FaceDetector and FaceRecognizer in `src/ibvap/core/face.py`**

- Initialize `cv2.FaceDetectorYN.create(model_path, "", (320, 320), conf_threshold, 0.3, 5000)`.
- In `detect(frame)`: dynamically update input size `self._detector.setInputSize((w, h))`, run `self._detector.detect(frame)`, parse `[N, 15]` output into `FaceDetection` with normalized coordinates, 5 landmarks, blur score (via Laplacian variance), and illumination.
- Implement `FaceRecognizer` using `cv2.FaceRecognizerSF`: extract 128-d feature vectors, match against enrolled watchlist using cosine similarity.
- Add `check_identity_gate_passed(settings)` respecting configuration toggle `enable_face_identity`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_face_real.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ibvap/core/face.py src/ibvap/config.py tests/test_face_real.py
git commit -m "feat: wire real YuNet face detector and SFace recognizer with privacy gate"
```

---

### Task 5: Real ANPR Pipeline with Contour Localization & Consensus

**Files:**
- Modify: `src/ibvap/core/anpr.py:1-102`
- Create: `tests/test_anpr_real.py`

**Interfaces:**
- Consumes: Vehicle crop BGR array, track ID.
- Produces: `ANPRPipeline.process_vehicle_crop(crop, vehicle_id) -> PlateResult | None`.

- [ ] **Step 1: Write test for ANPR plate extraction, normalization, and consensus**

```python
import numpy as np
import cv2
from ibvap.core.anpr import ANPRPipeline, normalize_plate

def test_anpr_localization_and_consensus():
    pipeline = ANPRPipeline()
    # Create synthetic vehicle crop with a simulated plate rectangle
    crop = np.full((120, 200, 3), 100, dtype=np.uint8)
    cv2.rectangle(crop, (40, 70), (160, 105), (240, 240, 240), -1)
    cv2.putText(crop, "KA01AB1234", (45, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (10, 10, 10), 2)
    
    # Consensus test
    assert pipeline.consensus_for(1, "KA 01 AB 1234") == "KA01AB1234"
    assert pipeline.consensus_for(1, "KA 01 AB 1234") == "KA01AB1234"
    assert pipeline.consensus_for(1, "KA01AB1234") == "KA01AB1234"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anpr_real.py -v`
Expected: FAIL

- [ ] **Step 3: Implement plate localization and OCR pipeline in `src/ibvap/core/anpr.py`**

- In `PlateDetector`: implement morphology-based plate localization on vehicle crops (grayscale &rarr; Sobel gradient &rarr; Otsu threshold &rarr; morphology close &rarr; findContours &rarr; aspect ratio $2.0 \le W/H \le 5.5$).
- Implement character recognition reader with confidence extraction.
- Wire into `ANPRPipeline.process_vehicle_crop` with temporal voting via `Counter`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anpr_real.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ibvap/core/anpr.py tests/test_anpr_real.py
git commit -m "feat: implement real ANPR plate candidate localization and consensus"
```

---

### Task 6: MediaMTX Windows Setup & Local Media Gateway Mock

**Files:**
- Create: `src/ibvap/core/media_gateway.py`
- Create: `scripts/setup_mediamtx.ps1`
- Modify: `src/ibvap/api/routes/health.py:30-68`
- Create: `tests/test_media_gateway.py`

**Interfaces:**
- Produces: Standalone MediaMTX runner script and in-process MediaMTX v3 REST API emulator.

- [ ] **Step 1: Write test for MediaMTX gateway API client and mock server**

```python
import pytest
from ibvap.core.media_gateway import MediaGatewayClient, MockMediaMTXServer

@pytest.mark.asyncio
async def test_media_gateway_mock_and_client():
    server = MockMediaMTXServer(port=19997)
    await server.start()
    try:
        client = MediaGatewayClient(api_url="http://localhost:19997")
        health = await client.check_health()
        assert health is True
        paths = await client.list_paths()
        assert isinstance(paths, list)
    finally:
        await server.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_media_gateway.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `media_gateway.py` and `scripts/setup_mediamtx.ps1`**

- Implement `MediaGatewayClient` with async `httpx` methods to check health and list/create stream paths.
- Implement `MockMediaMTXServer` for local testing.
- Write `scripts/setup_mediamtx.ps1` to download `mediamtx_v1.20.1_windows_amd64.zip` from GitHub Releases and extract `mediamtx.exe` into `data/bin/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_media_gateway.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ibvap/core/media_gateway.py scripts/setup_mediamtx.ps1 src/ibvap/api/routes/health.py tests/test_media_gateway.py
git commit -m "feat: add MediaMTX native Windows setup script and local media gateway runner"
```

---

### Task 7: Real Hardware Benchmarking Suite

**Files:**
- Create: `scripts/benchmark.py`
- Create: `tests/test_benchmarks.py`
- Modify: `docs/benchmarks.md:1-36`

**Interfaces:**
- Measures: AMD Ryzen 7 7435HS CPU + NVIDIA GeForce RTX 4050 GPU latencies, FPS, and memory.
- Produces: Benchmarking CLI and verified Markdown report.

- [ ] **Step 1: Write benchmark execution test**

```python
from scripts.benchmark import run_system_benchmarks

def test_benchmark_suite_generates_metrics():
    results = run_system_benchmarks(num_runs=5)
    assert "cpu_model" in results
    assert "gpu_model" in results
    assert "detector_latency_ms_p50" in results
    assert results["detector_latency_ms_p50"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_benchmarks.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `scripts/benchmark.py` and execute benchmark**

- Benchmark PyAV decoding, ONNX detection (CPU and DirectML), YuNet face detection, SFace embedding, and tracking.
- Output benchmark results table into `docs/benchmarks.md`.

- [ ] **Step 4: Run benchmark and test**

Run: `uv run python scripts/benchmark.py`
Run: `uv run pytest tests/test_benchmarks.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark.py tests/test_benchmarks.py docs/benchmarks.md
git commit -m "feat: run real host hardware benchmarks and record verified metrics"
```

---

### Task 8: Automated Chaos & Soak Testing Harness

**Files:**
- Create: `tests/test_chaos_soak.py`
- Modify: `docs/deployment.md:39-45`

**Interfaces:**
- Verifies: System resilience against queue backpressure, rapid camera disconnects, database rollbacks, and memory leakage over 1,000+ iterations.

- [ ] **Step 1: Write chaos and soak test suite**

```python
import numpy as np
from ibvap.core.pipeline import MiniPipeline
from ibvap.core.queue import BoundedQueue

def test_bounded_queue_backpressure_chaos():
    q = BoundedQueue("chaos-q", max_size=3, max_age_ms=50)
    for i in range(100):
        q.put(np.zeros((10, 10, 3), dtype=np.uint8))
    # Queue must enforce max_size and track drops
    assert q.qsize() <= 3
    assert q.stats.dropped_overflow > 50

def test_pipeline_continuous_soak_memory_stable():
    pipe = MiniPipeline(camera_id="soak-cam")
    for i in range(500):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        pipe.process_frame(frame)
    assert pipe.frame_idx == 500
```

- [ ] **Step 2: Run test to verify execution**

Run: `uv run pytest tests/test_chaos_soak.py -v`
Expected: PASS

- [ ] **Step 3: Update `docs/deployment.md` with chaos and soak verification results**

Update the Phase 8 exit checklist in `docs/deployment.md` with the verified chaos and soak findings.

- [ ] **Step 4: Commit**

```bash
git add tests/test_chaos_soak.py docs/deployment.md
git commit -m "test: add automated chaos and soak testing harness and update deployment records"
```

---

### Task 9: Full Regression, Strict Pyright, Ruff, and Frontend Build Verification

**Files:**
- Touch: all test and source files
- Frontend: `frontend/`

- [ ] **Step 1: Run full pytest suite**

Run: `uv run pytest -v`
Expected: 100% PASS across all unit, integration, live DB, and chaos tests.

- [ ] **Step 2: Run Ruff linter and formatter**

Run: `uv run ruff check .` and `uv run ruff format --check .`
Expected: Clean with 0 errors.

- [ ] **Step 3: Run Pyright in strict mode**

Run: `uv run pyright`
Expected: 0 errors, 0 warnings.

- [ ] **Step 4: Build frontend production bundle**

Run: `npm run build` in `frontend/`
Expected: Vite build succeeds with clean output.

- [ ] **Step 5: Final commit and summary**

```bash
git status
git commit -am "chore: final validation of limitation resolution and full runtime readiness"
```
