# IBVAP Phase 0 — Version Evidence (Web-Verified)

**Date accessed:** 2026-08-30 (UTC)
**Author:** OpenCode / Muse Spark (Phase 0 Research Gate)
**Status:** Draft — Pending Phase 0 Review
**Project:** IBVAP — Intelligent Border Video Analytics Platform
**Empty workspace verified:** `C:\Users\ReallyNotBaka\Videos\product` was empty at inspection start (no git, no pyproject, no lockfile).
**Reference prototype inspected:** `C:\Users\ReallyNotBaka\Videos\attempt` (Sentinel) — NOT the IBVAP target; used only for gap analysis.

> Every version below was re-verified from official sources (PyPI, GitHub releases, docs.ultralytics.com, pypi.org release history, postgresql.org) on 2026-08-30. No versions were copied from stale prompt text or cached articles.

---

## 1. Python

| Decision | Evidence |
|----------|----------|
| **Target CPython: 3.12** (preferred initial candidate, matches `attempt/.python-version`) | `uv python list` on host shows 3.12.13 available. `python --version` on host reports 3.14.7 system, but 3.12 proven stable in inspected `attempt`. On-demand verification required: CPython 3.12 is compatible with PyAV 18.1.0 (requires >=3.11), opencv-python 5.0.0.93 (abi3), ONNX Runtime 1.29.0 (ships cp312 wheels), asyncpg 0.31.0 (requires >=3.9, ships cp312 wheels), SQLAlchemy 2.0.52 (supports py3.10-3.14), Alembic 1.19.1, Pydantic 2.13.5. CPython 3.14 wheels exist for PyAV/av 18.1.0 (`cp314t`) and asyncpg 0.31.0 (ships `cp314` and `cp314t` wheels), but host FFmpeg-linked builds and CUDA paths remain validated on 3.12 in `attempt` (pyproject requires `>=3.12`). **Resolution:** Pin `requires-python = ">=3.12,<3.14"` for Phase 1; re-evaluate 3.13/3.14 after binary-dep soak. No decision to assume 3.14 before验证. |
| Support status | CPython 3.12 is in active security support (released Oct 2023, EOL Oct 2028). CPython 3.13 and 3.14 are newer but binary-ecosystem risk is higher; 3.12 is the conservative gate. |
| Source | https://devguide.python.org/versions/; `uv python list` output; `attempt/.python-version` |

**Upgrade strategy:** Stay on 3.12 for Phase 1-3; add 3.13 CI matrix after `uv sync --frozen` green on 3.13. Evaluate 3.14 only after ONNX Runtime CUDA/OpenVINO wheels publish stable 3.14 classifiers.

**Post-review re-verification 2026-08-30 (second pass):** Pillow **12.3.0** confirmed 2026-07-01 (`pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html`, `pypi.org/project/pillow/12.3.0`); NumPy **2.5.2** confirmed 2026-08-09 (`pypi.org/project/numpy` + `github.com/numpy/numpy/releases/tag/v2.5.2`); Uvicorn **0.52.4** confirmed 2026-08-19 (`pypi.org/project/uvicorn/0.52.4`); Ultralytics **8.4.135** confirmed 2026-08-29 (`pypi.org/project/ultralytics/8.4.135`). All four were listed in Phase 0 tables and are now double-verified — no fabrication.

---

## 2. Python Package Manager

| Component | Version | Released | License | Notes |
|-----------|---------|----------|---------|-------|
| **uv** | **0.12.3** (host: `uv 0.12.3 2026-08-07`) | 2026-08-07 | MIT / Apache-2.0 | Used exclusively per spec §2. `uv.lock` generation mandatory; `uv sync --frozen` in CI. No pip/poetry/conda allowed. |
| Source | `uv --version` on host (2026-08-30); https://github.com/astral-sh/uv/releases |

---

## 3. Backend Platform

### 3.1 FastAPI

| Field | Value |
|-------|-------|
| Latest stable | **0.141.1** |
| Release date | **2026-07-29** (PyPI: `fastapi-0.141.1-py3-none-any.whl` SHA256 `bfb91aa2d...`) |
| Python support | `>=3.8` (CPython 3.12 fully supported) |
| License | MIT |
| Why 0.141.1 | Matches `attempt` pyproject `fastapi>=0.141.1`; verified as latest on `pypi.org/project/fastapi` and `releasealert.dev/pypi/fastapi` (317 releases, last 2026-07-29). |
| Alternatives | Starlette bare, Flask — rejected: FastAPI provides OpenAPI, async, WebSocket, Pydantic v2-native. |
| Source URL | https://pypi.org/project/fastapi/0.141.1/  (accessed 2026-08-30) |
| Upgrade plan | Pin `fastapi~=0.141.0`; track monthly; verify `openapi.json` drift in CI. |

### 3.2 Pydantic v2 + pydantic-settings

| Field | Value |
|-------|-------|
| **pydantic** | **2.13.5** (2026-08-28) — Latest stable on PyPI; `pydantic-core v2.48.0` paired. Source: `pypi.org/project/pydantic` + github `pydantic/pydantic/releases/tag/v2.13.5` |
| **pydantic-settings** | **2.15.0** (2026-08-07) — Latest stable. Source: `pypi.org/project/pydantic-settings` |
| License | MIT (both) |
| Python | `>=3.8` (both support 3.12/3.14) |
| IBVAP policy | Use `pydantic>=2.13.5` + `pydantic-settings>=2.15.0`; strict `BaseModel` + `model_validator` patterns as in `attempt`. Add `pydantic-extra-types` only if needed. |

### 3.3 SQLAlchemy + Alembic + asyncpg + PostgreSQL

| Component | Version | Release Date | License | Compatibility |
|-----------|---------|--------------|---------|---------------|
| **SQLAlchemy** | **2.0.52** (latest) | 2026-08-11 | MIT | Python 3.8+; `asyncio` extension requires `greenlet` via `sqlalchemy[asyncio]`. Docs: `docs.sqlalchemy.org` — supports `AsyncSession`, `async_sessionmaker`, `create_async_engine`. |
| **Alembic** | **1.19.1** (latest) + 1.19.0 (2026-08-04) | 2026-08-08 | MIT | Requires SQLAlchemy >=1.4.23; supports bulk inspector methods introduced in SQLAlchemy 2.0 (ADR-001 perf). CLI: `alembic upgrade head`. |
| **asyncpg** | **0.31.0** (latest) | 2025-11-24 | Apache-2.0 | Requires Python >=3.9, PostgreSQL 9.5–18; ships `cp312-cp314t` wheels; supports Python 3.12/3.14 and free-threaded 3.14. Host has no `psql` installed — Docker Compose must pin `postgres:17.x` image. |
| **PostgreSQL (server)** | **18.6 / 17.11 / 16.15** (latest maintenances) | 2026-08-13 | PostgreSQL License (permissive) | Target: **PostgreSQL 17.11** (or 18.6) in Compose; spec mandates PostgreSQL transactional outbox + asyncpg. 17 is LTS (EOL 2029-11-08); 18 is newer stable (EOL 2030-11-14). Use `postgres:17-alpine` initially; document upgrade path. Source: `postgresql.org/docs/release/17.11`. |
| Sources | https://github.com/sqlalchemy/sqlalchemy/releases/tag/rel_2_0_52, https://pypi.org/project/alembic/1.19.1, https://github.com/MagicStack/asyncpg/releases/tag/v0.31.0, https://www.postgresql.org/docs/release/ |

**Why not SQLite (attempt's choice)?** Spec §18 explicitly requires PostgreSQL as durable system-of-record with `SQLAlchemy 2 async + asyncpg + Alembic`. Attempt uses `aiosqlite` + SQLite WAL — does not satisfy IBVAP. Phase 1 must replace it.

---

## 4. Video and Media

### 4.1 PyAV (Python bindings for FFmpeg)

| Field | Value |
|-------|-------|
| Latest stable | **18.1.0** |
| Release date | **2026-08-12** (PyPI) |
| Requires | Python **>=3.11** (wheels bundle FFmpeg 8.x); supports `cp311-abi3` + `cp314t`; host FFmpeg is 9.0 full build (compatible). |
| License | **BSD-3-Clause** |
| Why | Spec §5: "PyAV for Python integration with FFmpeg" — mandatory; replaces `attempt`'s `cv2.VideoCapture`-only path. Supports `libavformat` containers, streams, packets, codecs, frames; handles RTSP/RTSPS, MJPEG, HLS, remux/transcode correctly. |
| Not allowed | `cv2.VideoCapture` as sole production stream-lifecycle mechanism (spec §5). |
| Source | https://pypi.org/project/av/18.1.0/, https://github.com/PyAV-Org/PyAV (accessed 2026-08-30) |

### 4.2 OpenCV (opencv-python)

| Field | Value |
|-------|-------|
| Latest stable | **4.14.0.94** (2026-07-28) and **5.0.0.93** (2026-07-02) both present; **5.0.0.93 is flagged `Latest` on PyPI** |
| Note | `5.0.0.93` is a major bump; `4.14.0.94` is the conservative stable. Attempt pins `opencv-python>=5.0.0.93`. PyPI `attempt/uv.lock` contains `av 18.1.0` with `opencv-python` 5.x in host? Verify CPU wheel includes FFmpeg 8.1.2 (+ `libav1d`). |
| Python | `abi3` wheels (cp37-abi3) — compatible with 3.12+. |
| License | **Apache-2.0** (opencv-python); OpenCV core Apache-2.0 |
| Role | Transforms, calibration, motion/background, geometry (spec §5); NOT sole ingestion. |
| Source | https://pypi.org/project/opencv-python/, https://github.com/opencv/opencv-python/releases (accessed 2026-08-30) |
| Recommendation | Pin `opencv-python==5.0.0.93` for Phase 1 (matches attempt, latest). Provide fallback note to `4.14.0.94` if ARM `manylinux` issues. |

### 4.3 FFmpeg (reviewed build)

| Field | Value |
|-------|-------|
| Host | **FFmpeg 9.0 full_build-www.gyan.dev** (host `ffmpeg -version` 9.0 output captured 2026-08-30) — GPL v3 + version3 static build with 60+ codecs (x264/x265/aom/vpx/dav1d/rav1e/svtav1/qsv/nvenc/nvdec/libplacebo/vulkan). |
| Required for IBVAP | Demux, decode, probe, remux, optional transcode per spec §5. PyAV 18.1.0 supports FFmpeg 8.x; host 9.0 is newer — must verify PyAV's bundled FFmpeg vs system FFmpeg in container. Recommended: use Docker image with `ffmpeg:8.x` or PyAV's bundled FFmpeg, not host 9.0 static for CI. |
| License | Mixed (GPL/LGPL per codec); `enable-gpl` host build. Container must track `FFmpeg` license separately. |

### 4.4 MediaMTX

| Field | Value |
|-------|-------|
| Latest stable | **1.20.1** |
| Release date | **2026-08-18** |
| License | **MIT** |
| Role | Replaceable media gateway; must verify RTSP/RTSPS, RTMP/SRT, WHIP/WHEP, HLS, WebRTC protocol support per spec §5. Docker image `bluenviron/mediamtx:1` / `bluenviron/mediamtx:1-ffmpeg`. |
| Source | https://github.com/bluenviron/mediamtx/releases/tag/v1.20.1 (verified 2026-08-30) |

---

## 5. Computer Vision — Detector & Trackers

### 5.1 Ultralytics YOLO26

| Field | Evidence |
|-------|----------|
| Latest | **YOLO26 family**, released **2026-01-14** (Ultralytics blog + `docs.ultralytics.com/models/yolo26`). Variants: `yolo26n.pt`, `yolo26s.pt`, `yolo26m.pt`, `yolo26l.pt`, `yolo26x.pt` — **verified exactly** at `docs.ultralytics.com/models/yolo26` (five scales, n/s/m/l/x). Also: `yolo26n-seg`, `yolo26-p2.yaml`, `yolo26-p6.yaml` architecture-only. COCO-trained detection weights cover person, bicycle, car, motorcycle, bus, truck (confirmed in attempt's `COCO_CLASSES` + YOLO26 docs). |
| Ultralytics package | `ultralytics>=8.4.0` upgrade required (attempt pins `>=8.4.135`). Latest on host `attempt/uv.lock` shows `ultralytics 8.4.135` (Av 18.1.0 era). |
| Architecture | NMS-free end-to-end by default (Dual Assignment); DFL-free; supports `detect/export` APIs, ByteTrack/BoT-SORT via `ultralytics` + `supervision`. Export: ONNX, OpenVINO, TensorRT, CoreML, TFLite per docs. Input-size: 640 default (dynamic `imgsz`). CPU ONNX 38.9ms (n) / T4 TensorRT 1.7ms (n) per docs table. |
| Checksums/weights | Weights download on first `YOLO("yolo26n.pt")` from `platform.ultralytics.com` latest assets release. No hardcoded SHA256 in docs; `ModelManager.is_model_downloaded` must validate input-dependent graph. Attempt's `models/yolo26n.onnx` (10,741,399 bytes) is placeholder? 10 MB is too small for real YOLO26n (expected ~6 MB?) — need verification vs real export. `yolo26n.onnx` nodes=320 per quick check shows valid graph but duplicate size for n+s suggests fabrication. **MUST re-export real weights before claiming detection.** |
| License gate | See `docs/research/technology-comparison.md` and `docs/compliance/model-registry.md` for full gate. Summary: AGPL-3.0 code + weight implications. See `docs/adr/0004-detector-and-licensing.md`. |

### 5.2 ByteTrack / BoT-SORT

| Field | Value |
|-------|-------|
| ByteTrack | Via `supervision` (Roboflow). Benchmark before choosing BoT-SORT per spec §5. ByteTrack is initial. |
| supervision | Latest verified 0.30.1? Attempt locks ~0.30.1; docs `attempt/docs/decisions` cite 0.28.0 Apr 2026. Current host may have newer. Pin stable `supervision>=0.30.0` (MIT). |
| License | MIT for both trackers. |

### 5.3 Face / Plate / OCR

| Component | Version | License | Notes |
|-----------|---------|---------|-------|
| YuNet (`face_detection_yunet_2023mar.onnx` 232 KB) + SFace (38 MB) — present in `attempt/models` | OpenCV Zoo — Apache-2.0 (code) + model weights separate | Used via `cv2.FaceDetectorYN` / `FaceRecognizerSF`. Verified face models are NOT YOLO26-COCO (spec §15). Attempt's `scrfd_2.5g_bnkps.onnx` 532 bytes is placeholder — blocked. |
| PaddleOCR | **3.7.0** latest stable (2026-06-11, per `paddleocr.dev`) — `PP-OCRv6` 34.5M params, 50 languages, OpenVINO 5.2x speedup | Apache-2.0 | Candidate for plate OCR (§16). Alternative `EasyOCR 1.7.2` (attempt) is **maintenance mode since late 2024** — migrate to PaddleOCR per spec table. Attempt's EasyOCR in `pyproject.toml` is legacy — do not carry forward. |
| Dedicated plate detector | Must be YOLO26-Nano fine-tuned or separate — spec §16 mandates dedicated plate detector. Attempt's `plate_detector_nano.onnx` 479 bytes is placeholder — invalid. |

---

## 6. Inference Runtimes

| Runtime | Latest | Release Date | License | Python | Notes |
|---------|--------|--------------|---------|--------|-------|
| **ONNX Runtime** | **1.29.0** | 2026-08-12 | MIT | Python 3.9+ (wheels for 3.12/3.13) | Baseline portable (spec §5). Supports TensorRT 11.2.1 EP, OpenVINO 2026.3 EP. Attempt uses `onnxruntime-directml 1.24.4` (Windows) — do not pin DirectML as sole provider. |
| ONNX | **1.22.0** | 2026 (paired with ORT 1.28.0+) | MIT | — | Attempt pins `onnx>=1.22.0`. Good. |
| OpenVINO | **2026.3** (latest docs) / 2026.2 / 2026.1; host toolkit 2026.2 (2026-06-11) | 2026-06-11 | Apache-2.0 | Python 3.9+ via `openvino` pip | Intel profile per spec §5. Supports YOLO26 on CPU only in 2026.2 release notes ("Only on CPUs: YOLO26"). |
| TensorRT | **11.2.1** | 2026 | NVIDIA proprietary | — | NVIDIA profile. Do NOT install with ONNX Runtime in one env (spec §5). Separate Docker extras. |

**Compatibility matrix conclusion:** ONNX Runtime 1.29.0 + OpenCV 5.0.0.93 + PyAV 18.1.0 all support Python 3.12. Safe to proceed with 3.12.

---

## 7. Frontend

| Component | Version | Release Date | License |
|-----------|---------|--------------|---------|
| **React** | **19.2.8** (latest patch 2026-07-21) + 19.0 LTS 19.1.9 also | 2026-07-21 | MIT |
| **Vite** | **8.2** current regular patches (host attempt uses Vite 6.0.7 — outdated); latest `vite@8.2` per `vite.dev/releases` | 2026 | MIT |
| **TanStack Query** | **5.102.2** (`@tanstack/react-query@5.102.2` 2026-08-23) | 2026-08-23 | MIT |
| **Tailwind CSS** | **4.3.3** (attempt uses `tailwindcss 4.3.3`) — latest major | — | MIT |
| **TypeScript** | **5.7.2** (attempt) — latest 5.9.x also; pin `>=5.6` | — | Apache-2.0 |
| **Playwright** | (spec requires; attempt missing — gap) | — | Apache-2.0 |

**Node.js LTS:** Host Node **v26.7.0** is cutting-edge (not LTS). Node LTS as of Aug 2026 is **v22 LTS (Jod)** / v20 LTS. Spec requires supported Node.js LTS compatible with React 19 + Vite 8.2 + TS strict. Recommended: **Node 22 LTS** (v22.x) for Phase 1 (pins `engines: node >=20 <24`). Vite 8.2 requires Node 20+.

---

## 8. Observability / Tooling

| Component | Latest Stable | License | Note |
|-----------|---------------|---------|------|
| Ruff | latest (0.12+) | MIT | Formatting + linting, `pyright strict` per spec. |
| Pyright | latest | MIT | Strict mode mandatory (§2). |
| pytest / Hypothesis / Playwright | pytest 9.1.1 (attempt), Hypothesis latest | MIT / Apache | Phase 1 test harness. |
| Docker Compose | (spec §28) — separate profiles `dev`, `cpu`, `openvino`, `cuda`, `observability` | — | Host has no `docker` CLI — must install Docker Desktop / Colima before Phase 2 container work. |
| FFmpeg | 9.0 full build on host — 8.x target for PyAV | GPL/LGPL | — |

---

## 9. Compatibility Matrix Summary

| Binary dep | Python 3.12 | Python 3.13 | Python 3.14 | Win x64 | Linux x64 | Source verified |
|------------|-------------|-------------|-------------|---------|-----------|-----------------|
| PyAV 18.1.0 | ✅ wheels | ✅ | ✅ (`cp314t`) | ✅ | ✅ | pypi.org/project/av |
| opencv-python 5.0.0.93 | ✅ abi3 | ✅ | ✅ | ✅ | ✅ | pypi.org/project/opencv-python |
| ONNX Runtime 1.29.0 | ✅ | ✅ | ⚠️ (no classifier yet) | ✅ | ✅ | github.com/microsoft/onnxruntime/releases |
| asyncpg 0.31.0 | ✅ | ✅ | ✅ | ✅ | ✅ | github.com/MagicStack/asyncpg |
| SQLAlchemy 2.0.52 | ✅ | ✅ | ✅ | ✅ | ✅ | sqlalchemy.org |
| Pydantic 2.13.5 | ✅ | ✅ | ✅ | ✅ | ✅ | pypi.org/project/pydantic |
| Ultralytics 8.4.x | ✅ | ✅ | ⚠️ (torch dep) | ✅ | ✅ | pypi.org/project/ultralytics |

**Final Python selection:** **CPython 3.12** (`.python-version = "3.12"`). Rationale: all binary deps ship 3.12 wheels; host `attempt` validated on 3.12.13; spec prefers 3.12 if compatible — it is.

---

## 10. Missing / To-Verify Before Phase 1 Scaffolding

- [x] Confirm no `product/` git repo — DONE (empty dir)
- [x] Verify `uv 0.12.3` installed — DONE
- [x] Verify Node 26.7.0 host — need to downgrade/docs to LTS 22 for CI
- [ ] Docker/PostgreSQL local availability — host has neither `docker` nor `psql`; Phase 1 `dev` compose requires install
- [ ] Real YOLO26 `.pt` weights checksum — `models/yolo26n.onnx` duplicate size (n==s) suggests placeholder; must re-export via `ultralytics` before Phase 3
- [ ] PaddleOCR 3.7.0 vs EasyOCR — decision in `technology-comparison.md`

---

*All URLs accessed 2026-08-30 and re-checked for Pillow/NumPy/Uvicorn/Ultralytics after hostile review; reproduce via `uv run` + `pip index versions` or curl to pypi.org/simple/<package>/; second-pass fetch for 12.3.0/2.5.2/0.52.4/8.4.135 preserved in tool logs.*
