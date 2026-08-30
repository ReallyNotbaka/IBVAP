# IBVAP Compliance — Third-Party Licenses (Phase 0 Seed)

**Date:** 2026-08-30
**For:** IBVAP 0.1.0 pre-scaffold
**Format:** SPDX License Expressions + attribution requirements

> Every runtime dependency, model artifact, dataset, FFmpeg build, and frontend asset must appear here before production. This seed covers the Phase-1 baseline set verified in `version-evidence.md` / `dependency-matrix.md`. Copyleft network triggers are flagged for YOLO26.

---

## 1. Python Backend — Runtime Dependencies

| Package / Asset | Version Verified | SPDX License | Copyright Holder | Attribution Required | Copyleft / Network Clause | Source / Provenance | Approval |
|-----------------|------------------|--------------|------------------|----------------------|---------------------------|--------------------|----------|
| fastapi | 0.141.1 | `MIT` | Sebastián Ramírez | Yes (LICENSE) | No | PyPI + https://github.com/fastapi/fastapi | Approved |
| pydantic | 2.13.5 | `MIT` | Pydantic, Inc. | Yes | No | https://github.com/pydantic/pydantic | Approved |
| pydantic-settings | 2.15.0 | `MIT` | Pydantic | Yes | No | https://github.com/pydantic/pydantic-settings | Approved |
| sqlalchemy (+ greenlet ext) | 2.0.52 | `MIT` | Michael Bayer | Yes | No | https://www.sqlalchemy.org/license.html | Approved |
| alembic | 1.19.1 | `MIT` | Mike Bayer | Yes | No | https://alembic.sqlalchemy.org/ | Approved |
| asyncpg | 0.31.0 | `Apache-2.0` | MagicStack | Yes (NOTICE) | No | https://github.com/MagicStack/asyncpg/blob/master/LICENSE | Approved |
| av (PyAV) + bundled FFmpeg 8.x libs | 18.1.0 | `BSD-3-Clause` (PyAV) + FFmpeg `LGPL-2.1-or-later` / `GPL-2.0-or-later` per build flags | PyAV Org + FFmpeg | Yes (keep LICENSE.txt + FFmpeg notice) | No | https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt ; host FFmpeg `configuration: --enable-gpl` indicates GPL components enabled | **Review FFmpeg build** — host 9.0 full_build is GPL; container should use LGPL-configured 8.x or document GPL notice |
| opencv-python (+ opencv-contrib-python if used) | 5.0.0.93 | `Apache-2.0` + `LICENSE-3RD-PARTY.txt` (FFmpeg, libav1d, etc.) | OpenCV Team | Yes (keep 3rd-party file) | No | https://github.com/opencv/opencv-python/blob/master/LICENSE-3RD-PARTY.txt | Approved, track 3rd-party |
| numpy | 2.5.2 | `BSD-3-Clause` | NumPy Developers | Yes | No | https://numpy.org/doc/stable/license.html | Approved |
| pillow | 12.3.0 | `HPND` | Jeffrey A. Clark | Yes | No | https://pillow.readthedocs.io/en/stable/ | Approved |
| pyyaml | 6.0.3 | `MIT` | Kirill Simonov | Yes | No | https://github.com/yaml/pyyaml/blob/master/LICENSE | Approved |
| uvicorn | 0.52.4 | `BSD-3-Clause` | Tom Christie | Yes | No | https://github.com/encode/uvicorn | Approved |
| anyio / starlette / httpx | (fastapi deps) | `MIT` / `BSD-3-Clause` | — | Yes | No | — | Approved |
| ultralytics (YOLO runtime) | 8.4.135 | **`AGPL-3.0-only`** (code) | Ultralytics Inc. | **Yes + source disclosure** | **YES — §13 network use = distribution** | https://github.com/ultralytics/ultralytics/blob/main/LICENSE | **BLOCKED pending Enterprise grant** (see §4) |
| onnx | 1.22.0 | `MIT` | ONNX | Yes | No | https://github.com/onnx/onnx/blob/main/LICENSE | Approved |
| onnxruntime | 1.29.0 | `MIT` | Microsoft | Yes | No | https://github.com/microsoft/onnxruntime/blob/main/LICENSE | Approved |
| onnxruntime-directml (Windows only) | 1.24.4 | `MIT` | Microsoft | Yes | No | https://github.com/microsoft/onnxruntime/blob/main/LICENSE | Approved for dev |
| openvino (intel distribution) | 2026.3.0 | `Apache-2.0` | Intel | Yes | No | https://github.com/openvinotoolkit/openvino/blob/master/LICENSE | Approved |
| paddleocr / paddlepaddle | 3.7.0 | `Apache-2.0` | PaddlePaddle | Yes | No | https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE | Approved |
| easyocr (fallback) | 1.7.2 | `Apache-2.0` | Jaided AI | Yes | No | https://github.com/JaidedAI/EasyOCR/blob/master/LICENSE | Fallback only |
| supervision | 0.30.x | `MIT` | Roboflow | Yes | No | https://github.com/roboflow/supervision/blob/main/LICENSE | Approved |
| ruff / pyright / pytest / hypothesis / coverage | latest | `MIT`/`MPL-2.0` | — | Yes | No | — | Approved (dev) |

**Compliance entry for AGPL-triggered distribution:** If IBVAP is made available over network (SaaS, border-ops dashboard), AGPL §13 requires offering Corresponding Source to all users. Enterprise license removes this obligation per https://www.ultralytics.com/license.

---

## 2. Model Artifacts — Code vs Weight Licenses (separate)

| Artifact | Code/Architecture License | Weight License | Training Data | Notes |
|----------|---------------------------|----------------|---------------|-------|
| YOLO26 `yolo26{ n,s,m,l,x }.pt` (COCO) | `AGPL-3.0` (ultralytics repo) | **`AGPL-3.0`** (Ultralytics trained models, per FAQ) | COCO 2017 | Same copyleft as code — bundled weights inherit AGPL unless Enterprise |
| RF-DETR (alternative) | `Apache-2.0` | `Apache-2.0` | COCO + RF100-VL | Permissive escape hatch |
| YuNet 2023mar / SFace 2021dec | `Apache-2.0` (OpenCV Zoo) | **Verify per-model** (often Apache-2.0 but must read `opencv_zoo` per-model LICENSE) | WIDER FACE etc. | Separate review before prod |
| InsightFace SCRFD / ArcFace (if considered) | `MIT` (code) | **Non-commercial** (pretrained packs) | — | **Blocked for commercial gov use** without separate grant |
| fast-alpr plate detector | `MIT` | `MIT` | 65+ countries private+open | Preferred for plates |
| PaddleOCR PP-OCRv6 | `Apache-2.0` | `Apache-2.0` | Paddle mix | Approved |
| Multinex / Zero-DCE++ enhancer | `MIT` / research | `MIT` | Low-light datasets | Experimental |

---

## 3. Infrastructure & Frontend

| Asset | License | Notes |
|-------|---------|-------|
| PostgreSQL server (docker `postgres:17-alpine`) | `PostgreSQL License` (permissive, BSD-like) | https://www.postgresql.org/about/licence/ |
| MediaMTX 1.20.1 | `MIT` | https://github.com/bluenviron/mediamtx/blob/main/LICENSE |
| FFmpeg (host 9.0 full_build gyan.dev) | `GPL-3.0` (since `--enable-gpl`) — must include source offer if redistributing binary | Host build is GPL; container FFmpeg 8.x bundled via PyAV is LGPL-mapped — track separately |
| React 19.2.8, Vite 8.2, TanStack Query 5.102.2, Tailwind 4.3, TypeScript 5.7 | `MIT` / `Apache-2.0` | All permissive |
| Node.js 22 LTS runtime | `MIT` | — |
| Docker / Compose | `Apache-2.0` | — |

---

## 4. YOLO26 Licensing — Decision Record Summary

- **Default:** AGPL-3.0 code + AGPL-3.0 weights. Any IBVAP installation accessible over network to border operators triggers AGPL §13 source-distribution to those users.
- **Enterprise path:** Contact `https://www.ultralytics.com/license` for commercial grant that lifts AGPL obligation (pricing quoted per org/project; covers YOLO26 + future releases term-scoped).
- **IBVAP policy (Phase 0):** No `ultralytics` dependency added to `product/pyproject.toml` until written approval is recorded in `docs/compliance/model-registry.md` and `docs/adr/0004-detector-and-licensing.md`. Prototype work may use AGPL weights in isolated research directory (`attempt/`) but NOT in product image without gate pass.

---

## 5. Attribution & Notice File Plan

- Generate `THIRD_PARTY_NOTICES.txt` from `uv export` + `npm ls` at release (`generate-licenses --format plain` + `pip-licenses --format=plain` fallback).
- Include in Docker image at `/app/THIRD_PARTY_NOTICES.txt` and expose at `GET /api/v1/system/licenses` (JSON) + `GET /static/THIRD_PARTY_NOTICES.txt`.
- SBOM: CycloneDX 1.5 via `uv export --format cyclonedx1.5` + frontend via `npx @cyclonedx/cyclonedx-npm`.

---

## 6. Pending License Verifications (before Phase 1 build)

- [ ] Verify FFmpeg container license is LGPL-only (no `--enable-gpl` codecs like `libx264` under GPL vs `open264`).
- [ ] Verify YuNet/SFace per-model EULA in `opencv/opencv_zoo` release.
- [ ] Verify `multinex_nano` research repo LICENSE (not yet sourced).
- [ ] Confirm `openvino` Model Server proprietary boundary vs `openvino` core Apache-2.0.

*All SPDX identifiers per https://spdx.org/licenses/ ; re-verify on publish of `uv.lock`.*
