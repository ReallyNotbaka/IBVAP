# IBVAP Phase 0 — Report & Gate Decision

**Date:** 2026-08-30
**Project:** IBVAP — Intelligent Border Video Analytics Platform
**From:** OpenCode Principal Architect (Muse Spark, autonomous implementation)
**To:** Product Owner / Legal / Infra
**Gate:** Phase 0 → Phase 1 (Research & Licensing)
**Verdict reading path:** Start at §1 Executive Summary, then jump to §4 YOLO26 Licensing Gate for blocking decision, then §7 Phase 1 Plan for go/no-go.

---

## 1. Executive Summary

IBVAP Phase 0 started with an **empty repository at `C:\Users\ReallyNotBaka\Videos\product`** (verified no git, no pyproject, no lockfile) and a **reference prototype at `C:\Users\ReallyNotBaka\Videos\attempt`** (Sentinel). Phase 0 inspected the prototype, then re-verified every major dependency from authoritative sources (PyPI, GitHub releases, docs.ultralytics.com) on 2026-08-30.

**Deliverables produced (all present in `product/docs/`):**

- `docs/research/version-evidence.md` — stable versions, release dates, compatibility matrix, Python 3.12 choice
- `docs/research/technology-comparison.md` — accept/reject per subsystem with reasons
- `docs/compliance/dependency-matrix.md` — SPDX, redistribution, network-service, source URL per dep
- `docs/compliance/model-registry.md` — artifact registry stubs (YOLO26, YuNet/SFace, plate, PaddleOCR, enhancer)
- `docs/compliance/third-party-licenses.md` — SBOM seed + AGPL trigger flagged
- `docs/adr/0001-system-architecture.md` — modular monolith with isolated workers
- `docs/adr/0002-video-ingestion.md` — PyAV + MediaMTX + bounded queues, timing model
- `docs/adr/0003-inference-runtime.md` — ONNX Runtime baseline + openvino/cuda isolated profiles
- `docs/adr/0004-detector-and-licensing.md` — **YOLO26 gate (blocked)**
- `docs/adr/0005-event-delivery.md` — PG transactional outbox + HMAC C2 webhook
- `docs/threat-model.md` — 18 threats (STRIDE) mapped to spec §21 controls
- `docs/traceability.md` — REQ-01..REQ-24 matrix with evidence hooks
- This report + recommended Phase 1 plan (§7)

**Blocking decision:** **YOLO26 licensing gate is BLOCKED** — ULTRALYTICS YOLO26 code + weights are **AGPL-3.0**; IBVAP's intended closed/commercial/government deployment **conflicts** with AGPL §13 network obligation without an Enterprise grant. No `ultralytics` dependency may enter `product/` until gate is ratified. Alternative RF-DETR (Apache-2.0) documented as fallback.

**Next step:** Ratify Branch A (Enterprise) or Branch B (Apache alternative) at joint legal/eng review, then scaffold Phase 1 foundation (uv project, PG migrations, API skeleton, frontend tokens, Compose dev profile, CI harness). Detector work stays in `attempt/` research until then.

---

## 2. Repository Inspection — What Was Found

### 2.1 Product workspace (`C:\Users\ReallyNotBaka\Videos\product`)

- **Empty.** No hidden files, no `.git`, no `pyproject.toml`, no `uv.lock`. Confirmed 2026-08-30 15:38 UTC.
- Host tooling: `uv 0.12.3`, `Python 3.14.7` (system) + `3.12.13` via uv managed, `Node 26.7.0`, `FFmpeg 9.0-full_build`, **no `docker`, no `psql`**.

### 2.2 Reference prototype (`C:\Users\ReallyNotBaka\Videos\attempt` — Sentinel v0.1.0)

| Area | Finding | Verdict |
|------|---------|---------|
| Package | `pyproject.toml` name `sentinel`, `requires-python >=3.12`, `.python-version 3.12`, deps include `ultralytics>=8.4.135`, `opencv-python>=5.0.0.93`, `av 18.1.0` present via lock, `easyocr 1.7.2`, `onnxruntime-directml`, `.venv` present, `uv.lock` committed (1.x rev) | Useful for reuse patterns, not spec-compliant |
| Frontend | `frontend/package.json` `react 19.0.0`, `vite 6.0.7`, `tailwind 4.3.3`, pages `SourceSelect`, `Dashboard` + canvases | React base is reusable; Vite **outdated** (need 8.2), TanStack Query/Radix/Konva/Playwright missing |
| Pipeline | `src/sentinel/core/pipeline.py` single-threaded `Pipeline` consuming `VideoSource` (`cv2.VideoCapture`) → `ObjectDetector` (`supervision`) → `MultiObjectTracker` (ByteTrack) → `FaceDetector` (`FaceDetectorYN`) → `PlateRecognizer` (EasyOCR + morph heuristic) → `ZoneManager` → `EventBus` SQLite WAL + WS | Core domain logic is portable; ingestion must be rewritten (PyAV+MediaMTX), DB must be Postgres+outbox, SSRF/state-machine missing |
| Models dir | `models/yolo26n.onnx 10,741,399 B`, `yolo26s.onnx same size duplicate`, `yolo26m/l/x 479 B placeholders`, `face_detection_yunet 232k` valid, `sface 38MB` valid, `scrfd 532 B` placeholder, `plate 479 B` placeholder, `multinex 137 B` placeholder, `fast_build_models.py` correctly refuses to synthesize | Placeholders must NOT be copied to product; face Zoo models are usable after hash; YOLO weights need fresh export |
| Docs | `docs/decisions/000-007` existing research (Aug 2026 web-verified) | Informative; Phase 0 re-verified and superseded with fresh evidence docs |
| Tests | `uv run pytest -v` **19/19 passed** (54s, deprecation warnings for EasyOCR `torch.ao.quantization`) | Harness works — proves not to trust green alone; port tests after DB replacement |
| .git | `master` branch, **no commits yet** (untracked files only), `.gitignore` missing `uv.lock`? actually includes but also missing `models/*.pt` ignore refinement | New product repo must init fresh with proper `.gitignore` |
| Secrets | No committed camera URLs/secrets found in inspect; but `attempt` allows `allow_origins=["*"]` (CORS wildcard) — must be hardened |

**Incomplete / contradictory implementation** per spec §3 checklist:
- No PG/Alembic, no OIDC/RBAC, no bounded queue metrics, no SSRF guard, no transactional outbox, no S3 interface, no schedule/retention/legal-hold, no WHEP/HLS, no `DetectorProvider` abstraction beyond `ObjectDetector` class.

---

## 3. Version Research — Headlines

| Decision | Evidence date | Source |
|----------|---------------|--------|
| **Python 3.12** pinned for Phase 1 (`requires-python >=3.12,<3.14`) — all binary deps ship 3.12 wheels; 3.14 wheels exist but unverified at scale | 2026-08-30 | `version-evidence.md §1` |
| **FastAPI 0.141.1** latest (2026-07-29) — matches prototype; Pydantic 2.13.5 (2026-08-28) + settings 2.15.0 (2026-08-07) | same | PyPI + GitHub |
| **SQLAlchemy 2.0.52** + **Alembic 1.19.1** + **asyncpg 0.31.0** + **PostgreSQL 17.11/18.6** (target `17-alpine`) | same | sqlalchemy.org, pypi.org, postgresql.org |
| **PyAV 18.1.0** (2026-08-12, FFmpeg 8.x) + **opencv-python 5.0.0.93** | same | PyPI |
| **ONNX Runtime 1.29.0** (2026-08-12) + **OpenVINO 2026.3** + **TensorRT 11.2.1** separate profiles | same | github.com/microsoft/onnxruntime |
| **MediaMTX 1.20.1** (2026-08-18) | same | github.com/bluenviron/mediamtx |
| **PaddleOCR 3.7.0 PP-OCRv6** (Apache-2.0, 50-lang) — selected over EasyOCR 1.7.2 (maintenance) | same | paddleocr.dev |
| **React 19.2.8** + **Vite 8.2** + **TanStack Query 5.102.2** + Node **22 LTS** (host is non-LTS 26.7 — doc drift noted) | same | github.com/facebook/react, vite.dev |
| **FFmpeg host 9.0** detected (gyan.dev) vs PyAV 8.x bundled — note drift for container | same | host `ffmpeg -version` |

Full per-package table with release dates, support status, Python arch, licenses in `dependency-matrix.md`. Replacement/upgrade cadence documented.

---

## 4. YOLO26 Licensing Gate — **BLOCKED**

### 4.1 Verified facts (authoritative, 2026-08-30)

- **YOLO26 is real, GA since Jan 14, 2026** — five variants `yolo26{ n,s,m,l,x }.pt` confirmed at `docs.ultralytics.com/models/yolo26`; package `ultralytics>=8.4.0` (prototype uses 8.4.135).
- **NMS-free + DFL-free** by default; exports ONNX/OpenVINO/TensorRT/CoreML; STAL small-object aware — matches spec §4 expectations.
- **Code LICENSE:** `AGPL-3.0` (`github.com/ultralytics/ultralytics` + `github.com/ultralytics/yolo26` both list AGPL-3.0).
- **Weights LICENSE — same:** Per https://www.ultralytics.com/license FAQ (queried live): *"Are Ultralytics YOLO trained models licensed under AGPL-3.0? **Yes**. All Ultralytics YOLO trained models fall under AGPL-3.0 by default."*

### 4.2 Why IBVAP conflicts with pure AGPL

Ultralytics license page (live fetch 2026-08-30) lists **Enterprise triggers** that apply directly to IBVAP:

- Internal business tools / private company applications
- Any commercial product or service
- Proprietary / closed-source software
- SaaS platforms / APIs / cloud systems using YOLO behind the scenes
- Embedded deployments in hardware, edge devices, robotics, cameras
- Using custom-trained/fine-tuned YOLO models in proprietary/commercial setting
- Internal private R&D not open-sourced

IBVAP is **exactly** private deployment + internal business tool + embedded edge cameras at border outposts + closed-source/government system not offered as public source — i.e., textbook Enterprise trigger.

AGPL-3.0 §13: offering IBVAP over a network to operators **is distribution**; IBVAP must offer Corresponding Source of the **entire combined work** (not just YOLO) to every network user.

### 4.3 Gate outcome & required action

**Gate status:** `BLOCKED-UNTIL-ENTERPRISE-GRANT-OR-PERMITTED-ALTERNATIVE-RATIFIED`

Required steps per spec §4:

1. **Stop YOLO26 integration in `product/`** — do not `uv add ultralytics`, do not commit `.pt`/`.onnx` weights — until legal clears.
2. **Preserve `DetectorProvider` interface** — vendor-neutral abstraction planned; YOLO26 is one implementation.
3. **Research alternative:** **RF-DETR (Roboflow, ICLR 2026, Apache-2.0 code + weights, first >60 mAP COCO)** documented in `technology-comparison.md` and `ADR-0004` — fully permissive escape hatch.
4. **No silent substitution** — explicit decision meeting after legal review.
5. **Enterprise contact:** `https://www.ultralytics.com/license` (sales, ~24h response; covers YOLO26 + future terms, price per org/project).
6. **Document artifact-by-artifact** (SHA-256, code license vs weight license separately) in `model-registry.md` before any model enters product image.

**This gate is not a local failure — it is the correct outcome of Phase 0 research.** The phase passes as a research gate but the **detector integration milestone** is blocked.

---

## 5. Architecture Proposals — Consented (Pending Gate-Independent)

- **ADR-0001** (system): modular monolith with API / camera worker / durable-job worker / frontend + PG transactional outbox; defer K8s until single-node soak.
- **ADR-0002** (video): PyAV 18.1.0 demux/decode (not `VideoCapture` sole), MediaMTX 1.20.1 gateway, bounded latest-frame queues with explicit max/age/drop/metrics, PTS+time_base provenance, reconnect stream-epoch pinning, completed state machine DRAFT→STREAMING.
- **ADR-0003** (inference): ONNX Runtime 1.29.0 baseline everywhere; isolate `openvino` and `cuda` optional groups + Compose profiles; hot-swap via `InferenceEngine` pattern; never silent GPU→CPU fallback.
- **ADR-0005** (events): transactional outbox (`events+alerts+evidence_jobs+outbox` atomically) + relay `FOR UPDATE SKIP LOCKED` + per-client WS bounded queues (overlay durable via REST) + C2 signed HMAC webhook v1 with canonical digest, timestamp/nonce window, key rotation, DLQ.

All architecture decisions are **independent of YOLO choice** and can proceed to implementation.

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Enterprise license not funded → Phase 3 detector slice stalls | M | H | Parallel track 1: legal starts Enterprise quote now; Track 2: bench RF-DETR on same dataset (model-registry row) — decision within 1 sprint |
| Host has no Docker/PostgreSQL | Certain | H-Phase1 | Install Docker Desktop before Phase 1 `dev` compose; use `uv run --with psycopg[binary]` shim for local-only unit tests until PG up |
| FFmpeg 9.0 host drift vs PyAV 8.x bundled | M | M | Pin container FFmpeg to 8.1.2 via PyAV wheel's bundled libs; don't depend on host gyan.dev build |
| OpenCV 5.0.0.93 breaking change vs 4.14.0.94 | L | M | Pin `5.0.0.93` in `dependency-matrix` with fallback note; run headless `opencv-contrib-python-headless` variant in compose |
| Phone MJPEG parser not spec'd | M | M | Phase 2 HLS/MJPEG adapter must validate `multipart/x-mixed-replace` + JPEG SOI/EOI + size caps; never image-page as video |
| CORS wildcard in prototype leaks | L | H | Phase 1 API hardens to allowlisted `frontend_url`; test by negative case |
| Placeholder ONNX files mistaken for real | Certain (already duplicated) | H | `ModelManager._is_valid_onnx_model` input-dependency check ported day 1; `yolo26m/l/x 479B` rejected |

---

## 7. Exact Phase 1 Plan — BEFORE Broad Scaffolding (Gate-Aware)

**Phase 1 scope per spec §30:** *"Executable foundation: uv project, generated lockfile, API health/capabilities, PostgreSQL, Alembic, configuration, structured logging, frontend design foundation, Docker Compose development profile, CI, test harness"*

**Prerequisite (day 0):**

- [ ] Init fresh `product/` git: `git init -b main`, `.gitignore` (Python `.venv`, `data/db`, `frontend/dist`, `models/*.pt`, `models/*.onnx` except keepers, `*.db*`, `*.log`), `.python-version 3.12`, `README.md` with install/uv-only docs.
- [ ] Install Docker Desktop (Win32 host confirmed missing `docker`) — required for `postgres:17-alpine` + `mediamtx:1.20.1` compose.
- [ ] Legal: file Enterprise request (attach ADR-0004 + prototype scope) and parallel RF-DETR eval brief — report back within 1 week.

**Week 1 — uv + API shell + PG + CI:**

- [ ] `uv init` → `pyproject.toml` with `[project] name="ibvap"`, `requires-python = ">=3.12,<3.14"`, `dependencies` pinned ranges: `fastapi~=0.141.1, pydantic>=2.13.5, pydantic-settings>=2.15.0, sqlalchemy[asyncio]>=2.0.52, asyncpg>=0.31, alembic>=1.19, av>=18.1,<19, opencv-python>=5.0.0.93, numpy>=2, pillow, pyyaml, uvicorn[standard], python-multipart`, `[build-system] requires=["uv_build>=0.12.3"]` — **without `ultralytics`** until gate passes.
- [ ] `dependency-groups` `dev = ["pytest>=9.1.1","pytest-asyncio","httpx","ruff","pyright","hypothesis", "trufflehog/gitleaks pre-commit"]`.
- [ ] `uv lock` → commit `uv.lock` (real generated, not fabricated). Validate `uv lock --check` in CI.
- [ ] `ruff.toml` + `pyproject [tool.pyright] strict=true` + `pre-commit` hooks (ruff format/lint, pyright, gitleaks).
- [ ] `src/ibvap/app.py` — FastAPI app (no business routes yet) with `GET /api/v1/health` + `GET /api/v1/capabilities` (stub: `detector=YOLO26-blocked`, `media=pyav-18.1.0`, `db=postgres-17`).
- [ ] Config: `src/ibvap/config.py` typed `BaseSettings` + `config/default.yaml` validating `app/data/media`.
- [ ] Logging: structured JSON (OTEL-ready) to `data/logs/`.
- [ ] `compose.yaml` `dev` profile: `postgres:17-alpine@sha256:…` + `mediamtx:1.20.1` + `api` service (host bind for dev).
- [ ] `docker-compose.dev.yaml` → `api: build context . dockerfile Dockerfile.dev` (multi-stage `uv sync --frozen` layer cache).
- [ ] DB: `alembic init migrations` + initial migration `0001_init` (orgs/sites skeleton) → `alembic upgrade head` green on empty PG.
- [ ] Tests: `tests/test_version_evidence.py` (canary: asserts locked versions match `version-evidence.md`), `tests/test_api_health.py`, migration test `empty→latest`.

**Week 2 — Frontend foundation + API contract + health:**

- [ ] `frontend/` scaffold: `npm create vite@latest -- --template react-ts` with `react 19.2.8`, `vite 8.2`, `typescript 5.7 strict`, `tailwindcss 4.3`, `@tanstack/react-query 5.102.2`, `playwright` — **not** `vite 6.0.7`.
- [ ] Frontend `engines: {node: ">=20 <24"}`; commit `frontend/.nvmrc` with `22`.
- [ ] Root shell pages: `pages/EmptyState.tsx` (exactly `Connect phone camera` + `Use video footage` per UX override spec §4) — static only, no fake status.
- [ ] API groups stubbed per spec §19 but only `health/capabilities/system` wired in Phase 1; rest `501` shims with `problem-details` envelope.
- [ ] `api/v1/openapi.json` snapshot + drift check in CI.
- [ ] Playwright `empty-state.spec.ts` passes (no fake data).

**Quality bars to exit Phase 1 (per §31):**

- `uv lock --check` ✅, `uv sync --frozen` ✅, `ruff format --check` ✅, `ruff check` ✅, `pyright --warnings` 0 errors strict ✅, `pytest` ✅, `frontend: tsc --noEmit` ✅, `playwright` ✅, `alembic upgrade head` ✅ / `downgrade base -1 && upgrade head` ✅, no secrets in `gitleaks`, no AGPL code in `product/` until ratified, Docker `dev` compose `up` boots PG + API reachable.

**Phase 2 entry condition:** Phase 0 + Phase 1 gates both green AND detector-branch decision (Enterprise grant or RF-DETR ratified). If neither within sprint, Phase 2 proceeds with camera onboarding/SSRF/ingestion hardening **without** detector integration (zone drawing without live boxes is valid per storyboard preview-first flow).

---

## 8. Verification of Phase 0

- [x] Repository tree inspected (product emptiness + attempt layout + tests 19 green)
- [x] Lockfiles/config inspected (attempt `uv.lock` 1.x, `.python-version 3.12`, frontend `vite 6.0.7` outdated)
- [x] Tests executed (`uv run pytest -v` 19/19 pass, 54s; `yolo26n.onnx` graph has 320 nodes; placeholder `multinex/plate 4xxB` identified)
- [x] Containers/CI absent — noted; to be created Phase 1
- [x] License/secrets scan — no camera URLs found; CORS wildcard found as risk
- [x] Incomplete/contradictory implantation catalogued (§2.2 table)
- [x] All major deps re-verified with **live web sources** (PyPI, GitHub releases, docs.ultralytics.com) — recorded with URLs + dates in `version-evidence.md`
- [x] Exact versions determined via resolution, not stale prompt numbers
- [x] No broad scaffolding done before gate (only docs created)

---

## 9. Sign-Off

| Role | Decision | Signature / Date |
|------|----------|------------------|
| Engineering (Phase 0 author) | Phase 0 research complete; detector integration **blocked** until gate ratified; Phase 1 plan approved to proceed | OpenCode / 2026-08-30 |
| Legal / Procurement | Approve Enterprise grant request OR ratify RF-DETR alternative (record in ADR-0004) | — |
| Infra | Provision Docker/Compose + PG 17 + MediaMTX 1.20.1 for Phase 1 dev | — |

**Next artifact:** After sign-off, execute Phase 1 plan above and report Phase 1 gate with green CI + reproducible `uv sync --frozen` clone.

---

## Appendix — Hostile Self-Review (2026-08-30 post Phase 0)

*Trigger: user requested hostile principal-engineer review before proceeding.*

**Checks performed (spec §31):**
- Every claimed feature checked for hard-coded/fake status — **pass**: no fake preview, alerts, metrics; placeholders explicitly flagged invalid (479B/137B ONNX, duplicate n==s 10.7 MB) at `PHASE_0_REPORT.md:52` and `model-registry.md:7`.
- Exact versions from official sources — **pass after second fetch**: Pillow 12.3.0 2026-07-01, NumPy 2.5.2 2026-08-09, Uvicorn 0.52.4 2026-08-19, Ultralytics 8.4.135 2026-08-29 re-fetched and confirmed; FastAPI 0.141.1, Pydantic 2.13.5, SQLAlchemy 2.0.52, Alembic 1.19.1, asyncpg 0.31.0, PyAV 18.1.0, opencv-python 5.0.0.93, ONNX Runtime 1.29.0, MediaMTX 1.20.1, PaddleOCR 3.7.0 already verified. Second-pass appended to `version-evidence.md:8`.
- Fabricated metrics without source — **pass**: `43% faster`, `38.9ms CPU ONNX`, `60.1 mAP RF-DETR` all sourced to `docs.ultralytics.com/models/yolo26` table or ICLR paper, flagged as docs-cited not IBVAP-measured (`model-registry.md:51`).
- `uv.lock` generated not fabricated — **pass for Phase 0**: `product/` has no lock (correct — no scaffolding before gate); `attempt/uv.lock` is real generated (rev 3). Phase 1 will generate `product/uv.lock`.
- YOLO26 licensing approved — **correctly BLOCKED** (`ADR-0004:1`, `model-registry.md:53` `gate-blocked-until-license-decision`). No `ultralytics` in product deps.
- Face/plate dedicated, model licensing checksummed — **pass**: separate code vs weight licenses, SHA-256 PENDING (not fabricated), InsightFace non-commercial blocked (`third-party-licenses.md:49`).
- Credentials/metrics leakage — **pass**: threat model T-01..T-18 covers SSRF/DNS-rebind, credential split, redacted diagnostics, no raw frames in logs.
- Queues bounded, overload deterministic, timestamps/geometry correct, reconnect epoch safe — **pass**: ADR-0002 queue table + stream_epoch pinning.
- All 12 required docs present (`version-evidence`, `technology-comparison`, `dependency-matrix`, `model-registry`, `third-party-licenses`, `adr/0001..0005`, `threat-model`, `traceability`) — **pass**.

**Minor clarifications applied (no behavior change):** Added second-pass pillow/numpy/uvicorn/ultralytics dates to `version-evidence.md`; tightened FFmpeg host note. No scaffold yet — gate holds.

*All claims remain web-verified 2026-08-30; no detections, preview, alerts, metrics, or benchmarks are fabricated (spec §31 strict self-review).*
