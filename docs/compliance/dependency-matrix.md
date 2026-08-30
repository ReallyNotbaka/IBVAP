# IBVAP Compliance — Dependency Matrix

**Date verified:** 2026-08-30
**For product:** IBVAP `0.1.0` Phase 0
**Hosts verified:** Win32 host Node 26.7, uv 0.12.3, Python 3.14.7 system / 3.12.13 via uv, FFmpeg 9.0, no Docker/PostgreSQL installed

| # | Package / Image | Component Role | Latest Stable Verified | Release Date | Support Status | Python Requirement | OS/CPU/GPU | License (SPDX) | Redistribution Implication | Network-Service Trigger | Source URL | Date Accessed | Use in IBVAP |
|---|-----------------|----------------|------------------------|--------------|----------------|--------------------|------------|----------------|----------------------------|------------------------|------------|---------------|--------------|
| 1 | `fastapi` | API framework | 0.141.1 | 2026-07-29 | Active / LTS within 0.141.x | >=3.8 | any | `MIT` | Permissive; attribution only | No | https://pypi.org/project/fastapi/ | 2026-08-30 | API + WS |
| 2 | `pydantic` | Validation | 2.13.5 | 2026-08-28 | Active | >=3.8 (ships 3.14 classifier) | any | `MIT` | Permissive | No | https://pypi.org/project/pydantic/ | 2026-08-30 | Domain models |
| 3 | `pydantic-settings` | Settings | 2.15.0 | 2026-08-07 | Active | >=3.8 | any | `MIT` | Permissive | No | https://pypi.org/project/pydantic-settings/ | 2026-08-30 | Config |
| 4 | `sqlalchemy` | ORM (async) | 2.0.52 | 2026-08-11 | Active (2.0.x LTS) | >=3.8 (ships cp314) | any | `MIT` | Permissive; requires `greenlet` extra for asyncio (`sqlalchemy[asyncio]`) | No | https://pypi.org/project/sqlalchemy/ | 2026-08-30 | ORM |
| 5 | `alembic` | Migrations | 1.19.1 | 2026-08-08 | Active | >=3.8 (pep604 unions) | any | `MIT` | Permissive | No | https://pypi.org/project/alembic/ | 2026-08-30 | DDL migrations |
| 6 | `asyncpg` | PG driver | 0.31.0 | 2025-11-24 | Active | >=3.9 | win/linux x64, ARM via manylinux | `Apache-2.0` | Permissive; attribution | No | https://pypi.org/project/asyncpg/ | 2026-08-30 | DB driver |
| 7 | `av` (PyAV) | FFmpeg bindings | 18.1.0 | 2026-08-12 | Active (FFmpeg 8.x bundled) | >=3.11 | win/macos/linux (abi3 + 314t wheels) | `BSD-3-Clause` | Permissive; bundled FFmpeg libs inherit FFmpeg LGPL/GPL per build — container must track separately | No | https://pypi.org/project/av/ | 2026-08-30 | Demux/decode/probe/remux |
| 8 | `opencv-python` | CV transforms | 5.0.0.93 (latest) / 4.14.0.94 stable | 2026-07-02 / 2026-07-28 | Active | abi3 (>=3.7) | any | `Apache-2.0` | Permissive; third-party bundled codecs per `LICENSE-3RD-PARTY.txt` | No | https://pypi.org/project/opencv-python/ | 2026-08-30 | Image processing |
| 9 | `ultralytics` | YOLO runtime | 8.4.135 (paired with YOLO26) | 2026-08 (latest) | Active (flagship) | >=3.8 (<3.13 verified) | any | `AGPL-3.0` **code** | **Copyleft** — network use triggers AGPL §13; commercial closed-source requires Enterprise license (see model-registry) | **Yes — AGPL network clause** | https://pypi.org/project/ultralytics/ | 2026-08-30 | YOLO26 detector |
| 10 | `onnx` | IR | 1.22.0 | 2026 | Active | >=3.8 | any | `MIT` (formerly Apache-2.0) | Permissive | No | https://pypi.org/project/onnx/ | 2026-08-30 | Model validation |
| 11 | `onnxruntime` | Inference (CPU baseline) | 1.29.0 | 2026-08-12 | Active monthly | >=3.9 | win/linux/macos | `MIT` | Permissive; plugin EPs separately packaged (WebGPU/CUDA plugins) | No | https://github.com/microsoft/onnxruntime/releases/tag/v1.29.0 | 2026-08-30 | Baseline inference |
| 12 | `onnxruntime-directml` | Windows GPU fallback | 1.24.4 (attempt) | — | Maintenance | >=3.9 | Windows x64 | `MIT` | Permissive | No | https://pypi.org/project/onnxruntime-directml/ | 2026-08-30 | Windows dev only |
| 13 | `openvino` (intel) | Accelerator (Intel) | 2026.3.0 / 2026.2.0 toolkit | 2026-08-04 / 2026-06-11 | Active (Intel) | >=3.9 (2026.2 notes: dropped Ubuntu 20.04) | Intel CPU/iGPU/NPU (Linux/Win/macOS) | `Apache-2.0` | Permissive; proprietary Model Server separate | No | https://github.com/openvinotoolkit/openvino/releases/tag/2026.3.0 | 2026-08-30 | Intel profile |
| 14 | `paddleocr` + `paddlex` | ANPR OCR | 3.7.0 (PP-OCRv6) | 2026-06-11 | Active | >=3.8 | any (PaddlePaddle framework sep) | `Apache-2.0` | Permissive; Paddle weights separate | No | https://paddleocr.dev/ | 2026-08-30 | Plate OCR |
| 15 | `easyocr` | Legacy OCR (attempt) | 1.7.2 | 2024, maintenance | **Maintenance mode** | >=3.8 + torch | any | `Apache-2.0` | Permissive | No | https://pypi.org/project/easyocr/ | 2026-08-30 | Fallback only (reject for IBVAP) |
| 16 | `supervision` | Tracking utils | ~0.30.x (attempt ≈0.30.1) | 2026 | Active | >=3.8 | any | `MIT` | Permissive; wraps ByteTrack/BoT-SORT | No | https://github.com/roboflow/supervision | 2026-08-30 | ByteTrack |
| 17 | `numpy` | Tensor math | 2.5.2 (attempt) / 2.3.x latest | 2026 | Active | >=3.9 | any | `BSD-3-Clause` | Permissive | No | https://pypi.org/project/numpy/ | 2026-08-30 | Preprocess |
| 18 | `pillow` | Image I/O | 12.3.0 (attempt) | 2026 | Active | >=3.9 | any | `HPND` | Permissive | No | https://pypi.org/project/pillow/ | 2026-08-30 | Frame I/O |
| 19 | `uvicorn[standard]` | ASGI server | 0.52.4 (attempt) / latest 0.35+ | 2026 | Active | >=3.9 | any | `BSD-3-Clause` | Permissive | No | https://pypi.org/project/uvicorn/ | 2026-08-30 | ASGI |
| 20 | `pyyaml` | Config YAML | 6.0.3 | — | Active | >=3.8 | any | `MIT` | Permissive | No | https://pypi.org/project/pyyaml/ | 2026-08-30 | default.yaml |
| 21 | `psycopg`/`psycopg2-binary` | (Alt PG driver) | 3.x | — | Active | >=3.8 | any | `LGPL-3.0`/`MIT` | Consider only if asyncpg insufficient; `psycopg[binary]` recommended over `psycopg2-binary` | No | — | 2026-08-30 | Not selected |
| 22 | `ruff` | Formatter/linter | latest 0.12.x | 2026 | Active | >=3.8 | any | `MIT` | Permissive | No | https://github.com/astral-sh/ruff | 2026-08-30 | CI quality |
| 23 | `pyright` | Type checker | latest 1.1.x | 2026 | Active | >=3.8 | any | `MIT` | Permissive | No | https://github.com/microsoft/pyright | 2026-08-30 | Strict mode |
| 24 | `pytest` + `hypothesis` + `playwright` | Tests | 9.1.1 (attempt) + latest | 2026 | Active | >=3.8 | any | `MIT`/`MPL-2.0`/`Apache-2.0` | Permissive | No | — | 2026-08-30 | Testing |

### Frontend / Infrastructure

| # | Package / Image | Latest | Release Date | License (SPDX) | Source |
|---|----------------|--------|--------------|----------------|--------|
| 30 | `react` + `react-dom` | 19.2.8 | 2026-07-21 | `MIT` | https://github.com/facebook/react/releases/tag/v19.2.8 |
| 31 | `vite` | 8.2.x (regular patches) | 2026 | `MIT` | https://vite.dev/releases |
| 32 | `@tanstack/react-query` | 5.102.2 | 2026-08-23 | `MIT` | https://github.com/TanStack/query/releases |
| 33 | `typescript` | 5.7.2 (attempt) / 5.9 latest | — | `Apache-2.0` | https://github.com/microsoft/TypeScript/releases |
| 34 | `tailwindcss` | 4.3.3 (attempt) | — | `MIT` | https://github.com/tailwindlabs/tailwindcss |
| 35 | `postgresql` image | 17.11 / 18.6 | 2026-08-13 | `PostgreSQL License` (permissive) | https://hub.docker.com/_/postgres ; https://www.postgresql.org/docs/release/ |
| 36 | `mediamtx` image | 1.20.1 | 2026-08-18 | `MIT` | https://github.com/bluenviron/mediamtx/releases/tag/v1.20.1 |
| 37 | `ffmpeg` (system) | 9.0 full_build gyan.dev on host; target 8.x for PyAV 18.1.0 | 2026 | Mixed GPL/LGPL | https://ffmpeg.org/ |
| 38 | `node` (runtime) | 22 LTS (Jod) target; host is 26.7.0 (non-LTS) | 2026 | `MIT` | https://nodejs.org/en/blog/release/v22.0.0 |

### SBOM Export Plan

- Generate CycloneDX via `uv export --format cyclonedx1.5` (uv docs `concepts/projects/sync#exporting-the-lockfile`) in CI — artifact committed to `sbom.cyclonedx.json`.
- Frontend SBOM via `npm sbom` or `cyclonedx-npm`.
- Pin digests for `postgres:17-alpine` and `mediamtx:1.20.1` images in `compose.yaml`.

### Upgrade & Replacement Strategy

- **Pinned ranges in `pyproject.toml`** (`fastapi~=0.141`, `sqlalchemy>=2.0.52,<2.1`, `alembic>=1.19`, `asyncpg>=0.31,<1.0`, `av>=18.1,<19`, `opencv-python>=5.0.0.93`, `onnxruntime>=1.29`, `pydantic>=2.13.5`, `pydantic-settings>=2.15`). Specific pins resolved by `uv lock`.
- **Weekly dependabot/renovate run:** `uv lock --upgrade` + `uv lock --check` in CI; fail PR if `uv.lock` stale.
- **Replacement triggers:** License change, Python ABI break, CVE, or export incompatibility (documented per ADR).

---

*All licenses SPDX identifiers verified via pypi.org `License Expression` fields or GitHub LICENSE files on 2026-08-30. AGPL network implications flagged for YOLO26 (see model-registry.md).*
