# IBVAP Phase 0 — Technology Comparison (Web-Verified 2026-08-30)

**Status:** Accepted for Phase 1 scoping
**Reference rejected/accepted decisions follow ADR pattern; fuller rationale in `docs/adr/*.md`.**

---

## 1. Backend Platform

| Candidate | Latest (2026) | License | Pros | Cons | Verdict |
|-----------|---------------|---------|------|------|---------|
| **FastAPI 0.141.1** | 2026-07-29, MIT | Async native, Pydantic v2-native, OpenAPI auto, WebSocket, `CORSMiddleware`, `StaticFiles` | Tight spec fit; `attempt` proven at same version | Requires Starlette+anyio stack | **Selected** |
| Flask 3.x | MIT | Stable sync | Needs extension for async WS | **Rejected** — no native WS/SSRF guard hooks |
| Starlette bare | MIT | Minimal | No Pydantic integration | **Rejected** |

## 2. Data & Migrations

| Candidate | Latest | License | Notes | Verdict |
|-----------|--------|---------|-------|---------|
| **SQLAlchemy 2.0.52 + Alembic 1.19.1 + asyncpg 0.31.0 + PostgreSQL 17/18** | see version-evidence | MIT / Apache-2.0 / PG License | Async engine `create_async_engine("postgresql+asyncpg://")`, `async_sessionmaker`, transactional outbox, `pg_type` JSONB, RLS-ready scoping | **Selected** (spec §18 mandatory) |
| SQLite + aiosqlite | (attempt) | Public Domain | Zero-dep dev | **Rejected** — no concurrent writer HA, no LISTEN/NOTIFY, violates spec |
| Prisma Python | — | Apache-2.0 | TS-first | **Rejected** — not spec stack |

## 3. Configuration & Validation

| Candidate | Latest | License | Verdict |
|-----------|--------|---------|---------|
| **Pydantic 2.13.5 + pydantic-settings 2.15.0** | 2026-08-28 / 2026-08-07, MIT | **Selected** — strict `BaseModel`, `Field(ge=…)`, `model_validator`, `Settings` from env/YAML |
| dataclasses bare | stdlib | **Rejected** — no validation/coercion for 30+ config keys |

## 4. Video Ingestion & Media

| Candidate | Latest | License | Pros | Cons | Verdict |
|-----------|--------|---------|------|------|---------|
| **PyAV 18.1.0 (FFmpeg 8.x bundled) + FFmpeg build-reviewed** | 2026-08-12, BSD-3 | Precise `Container/demux/decode`, `Packet PTS/DTS/time_base`, `VideoFrame` PTS, `VideoReformatter`, sandboxable probe | Complex surface — must wrap | **Selected (mandatory §5)** |
| **opencv-python 5.0.0.93** (or 4.14.0.94) | 2026-07-02, Apache-2.0 | `cv2.resize` letterbox, `cvtColor`, `GaussianBlur` CLAHE, `findContours`, `polylines` | Cannot replace demux | **Selected** as image-processing companion (§5) |
| `cv2.VideoCapture` alone | — | Apache-2.0 | Simple | **Rejected as sole mechanism** (§5: "Do not use OpenCV VideoCapture as the sole production stream-lifecycle mechanism") |

**FFmpeg build comparison**

| Build | Verdict |
|-------|---------|
| gyan.dev 9.0 full_build (host) | Detected on host; 9.0 > PyAV 18.1.0 target 8.x — note drift |
| BtbN / conda-forge 8.1.2 | Recommended for container (matches `opencv-python 4.14.0.94` changelog FFmpeg 8.1.2 CVE-2026-8461) — use bundled wheels |

## 5. Media Gateway

| Candidate | Latest | License | Protocols | Verdict |
|-----------|--------|---------|-----------|---------|
| **MediaMTX 1.20.1** | 2026-08-18, MIT | RTSP/RTSPS, RTMP/SRT, WHIP/WHEP/WebRTC, HLS, recordings | **Selected** — replaceable per §5; image `bluenviron/mediamtx:1` |
| GStreamer `rtsp-server` | LGPL | RTSP heavy | **Rejected** — heavier C glue for Python |
| nginx-rtmp | BSD | RTMP/HLS only | **Rejected** — no WebRTC/WHIP |

## 6. Inference Runtimes (baseline + accelerators — isolated environments)

| Runtime | Latest | License | HW | Verdict |
|---------|--------|---------|----|---------|
| **ONNX Runtime 1.29.0** | 2026-08-12, MIT | CPU/CUDA/TensorRT/OpenVINO EPs | **Baseline portable** (§5) — every image includes ORT CPU |
| **OpenVINO 2026.2/2026.3** | 2026-06-11 / 2026-08-04, Apache-2.0 | Intel CPU/iGPU/NPU | **Intel profile** — separate `openvino` extras; YOLO26 supported "Only on CPUs" in 2026.2 notes |
| **onnxruntime-directml 1.24.4** | Windows DirectML EP | MIT | RTX 4050 fallback on Windows | **Host-only** — `attempt` used it; IBVAP `cpu` profile uses it on Windows, not Linux |
| **TensorRT 11.2.1 + CUDA** | NVIDIA proprietary | NVIDIA dGPU | **NVIDIA profile** — separate `cuda` extras, volume-isolated |

**Critical constraint:** "Do not install every accelerator stack into one environment" — separate `cpu`, `openvino`, `cuda` Docker Compose profiles + `pyproject.toml` optional dependency groups.

## 7. Detection & Tracking — Primary Decision

### 7.1 General Person/Vehicle Detector

| Candidate | Release | mAP (COCO) | Speed (T4) | Export | License | Verdict |
|-----------|---------|------------|------------|--------|---------|---------|
| **Ultralytics YOLO26 (n/s/m/l/x)** | Jan 2026, package `ultralytics 8.4.135` | 40.9–57.5 | NMS-free, DFL-free, ONNX/OpenVINO/TensorRT | **AGPL-3.0** code + weight implications | **Selected — subject to licensing gate (§4)** |
| RF-DETR (Roboflow) | ICLR 2026 | ~60 | Apache-2.0, DINOv2 | Apache-2.0 | **Alternative** — document as Enterprise escape hatch if AGPL blocked (see ADR-0004) |
| YOLO11 / YOLOv8 | Sept 2024 | lower | AGPL | **Rejected** — superseded |
| YOLO-NAS | 2023 | ~52 | Proprietary | **Rejected** — frozen after Deci→NVIDIA |

**Why YOLO26 wins if gate passes:** NMS-free simplifies postprocess; 43% faster CPU vs YOLO11 (spec §4), STAL small-object, COCO person/bus/car/truck/motorcycle/bicycle coverage for vehicle classification without extra classifier.

### 7.2 Tracker

| Candidate | License | Verdict |
|-----------|---------|---------|
| **ByteTrack (via `supervision`)** | MIT | **Selected — initial (§5)**; CPU-only, low-conf association, `sv.ByteTrack()` |
| BoT-SORT | MIT | **Benchmark before choosing** — needs appearance embedding licensing check (ReID) |
| OC-SORT | MIT | Noted, bench later |

### 7.3 Dedicated Face / Plate Detectors

| Task | Candidate | Why dedicated? | License gate |
|------|-----------|---------------|--------------|
| Face detection | **YuNet (`yunet_2023mar`) + SFace** via OpenCV Zoo, or SCRFD (InsightFace) | YOLO26-COCO does NOT detect faces (spec §4) | Zoo: Apache-2.0 + weight license; InsightFace pretrained weights need separate review (see model-registry) |
| Plate detection | YOLO26-Nano fine-tuned for plates OR `fast-alpr` style YOLO plate detector | YOLO26-COCO does NOT detect plates | Must be dedicated (§16) |
| Plate OCR | **PaddleOCR 3.7.0 PP-OCRv6** (preferred) | 50-lang unified, OpenVINO 5.2x speedup | Apache-2.0 — selected over EasyOCR 1.7.2 (maintenance mode since late 2024) |

## 8. OCR Comparison

| OCR | Latest | License | Verdict |
|-----|--------|---------|---------|
| **PaddleOCR 3.7.0 PP-OCRv6** | 2026-06-11 | Apache-2.0 | **Selected** — multi-frame consensus partner (§16); `PaddleX` CLI + `paddleocr` package |
| EasyOCR 1.7.2 | Maintenance | Apache-2.0 | **Rejected** — attempt uses it but upstream in maintenance; keep only as fallback adapter |

## 9. Frontend Stack

| Candidate | Latest (2026) | License | Verdict |
|-----------|---------------|---------|---------|
| **React 19.2.8 + Vite 8.2 + TypeScript 5.7 strict + TanStack Query 5.102.2 + Tailwind 4.3 + Radix/shadcn + Konva/SVG + WebRTC/WHEP + HLS fallback + Playwright** | 2026-07-21 / 8.2 / 5.7 / 2026-08-23 | MIT / MIT / Apache-2 / MIT | **Selected (spec §5 exactly)** |
| Next.js | MIT | **Rejected** — not spec; modular monolith serves static via FastAPI `StaticFiles` |
| Remix/Svelte | MIT | **Rejected** — spec mandates React |

**Node LTS:** Host is Node 26.7 (non-LTS). Pin **Node 22 LTS (Jod)** for CI (`engines: >=20 <24`) — Vite 8.2 requires Node 20+. `attempt` uses Vite 6.0.7 + Node unspecified — upgrade required.

## 10. Reliability / Storage

| Candidate | Verdict |
|-----------|---------|
| PostgreSQL transactional outbox + durable jobs (PG-backed) + bounded in-memory frame queues + filesystem evidence adapter (dev) + S3-compatible storage interface | **Selected (§5-6)** |
| Redis/Kafka frame bus | **Rejected** — spec §5: "Do not send frames through Celery, Redis, Kafka, or PostgreSQL … Use bounded local queues and intentionally drop old analysis frames" |
| MinIO-specific vendor lock | **Rejected** — S3 interface, no mandatory vendor (§5) |

## 11. Observability & Quality

| Component | Choice | License |
|-----------|--------|---------|
| OpenTelemetry + Prometheus + JSON structured logging | **Selected (§5)** |
| Ruff + Pyright strict + pytest + Hypothesis + Playwright + pre-commit | **Selected** |
| `uv_build>=0.12.3` build backend | MIT | Selected — matches `attempt`; verify `pyproject [build-system]` |

## 12. Notable Gaps in Attempt vs Spec

| Gap | Attempt | IBVAP Requirement | Phase addressed |
|-----|---------|-----------------|-----------------|
| DB | `aiosqlite` + SQLite WAL | PostgreSQL 17/18 + asyncpg + Alembic | Phase 1 (foundation) |
| Video ingestion | `cv2.VideoCapture` threaded only | PyAV demux + MediaMTX gateway + RTSP/RTSPS/MJPEG/WHIP/WHEP adapters | Phase 2 |
| Throttled ingestion state machine | No state machine | DRAFT→VALIDATING→…→STREAMING full FSM | Phase 2 |
| SSRF protection |None | Allowlist, DNS rebinding, redirect block, egress firewall | Phase 2 |
| YOLO weight validity | Placeholder 479-byte ONNX for m/s/l/x; n==s duplicate | Real exported weights, SHA-256, input-dependent validation | Phase 3 |
| Frontend | React 19 + Vite 6.0.7 + custom CSS | React 19.2.8 + Vite 8.2 + Tailwind + TanStack Query + Radix + Konva + Playwright | Phase 1 frontend foundation |

---

*All selections subject to ADR review in `docs/adr/0001–0005`. Alternatives documented with reason; replacement cost estimated in each ADR.*
