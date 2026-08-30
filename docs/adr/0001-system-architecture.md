# ADR-0001: IBVAP System Architecture — Modular Monolith (Phase 0)

- **Status:** Accepted (Phase 0)
- **Date:** 2026-08-30
- **Deciders:** IBVAP Principal Architect (OpenCode)
- **Related spec:** §5 Final Technology Direction, §6 Architecture, §22–28

## Context

IBVAP must ingest 1..N phone/IP camera streams, run analytics, emit durable events/evidence, and remain operable on remote sites with intermittent WAN. Spec mandates Python backend, PostgreSQL, MediaMTX gateway, and a **modular monolith** with separately runnable `API`, `camera worker`, `durable-job worker`, and `frontend` processes (§6) — not Kubernetes-initial.

Prototype `attempt/` uses a **single-process FastAPI + threaded Pipeline + SQLite + cv2.VideoCapture** (`src/sentinel/api/app.py:54-88 lifespan`, `src/sentinel/core/pipeline.py:50-464`). It lacks the outbox, S3 interface, state machine, and worker separation required per spec.

## Decision

Adopt **modular monolith** as specified, with bounded local queues and PostgreSQL transactional outbox:

```
Phone/IP Camera(s) ──> MediaMTX (RTSP/RTSPS/RTMP/SRT/WHIP→WHEP/HLS, MJPEG adapter)
                          │  └─> Browser WHEP/HLS playback (low-latency)
                          └─> PyAV demux/decode ──> Bounded latest-frame queue
                                                     ──> Sampling/preprocess
                                                       ──> YOLO26 (DetectorProvider)
                                                         ──> ByteTrack
                                                           ├─> Zone/rule engine
                                                           └─> Face/ANPR pipelines
                                                             └─> Event qualification
                                                               └─> Single PG transaction
                                                                     {event, alert, evidence_job, outbox}
                                                                     └─> outbox relay → store (FS/S3) + WS/C2 webhook
```

Deployment profiles (Compose):
- `dev` — API + Postgres 17 + MediaMTX 1.20.1 + Vite dev server
- `cpu` — prod image (ORT CPU + DirectML on Windows)
- `openvino` — + `openvino` extras
- `cuda` — + `tensorrt`/`cuda` ORT EPs (separate image, spec §5)
- `observability` — OTEL collector + Prometheus + Grafana (optional)

Specifically **not introduced in Phase 1:**
- Celery/Redis/Kafka for frames (§5: "Do not send frames through … Use bounded local queues")
- Kubernetes (§6: "Do not introduce Kubernetes initially")
- PostGIS for image polygons (§18)

## Consequences

### Positive
- One transactional boundary for event durability (§17).
- WAN-resilient: local ingest/inference/events/evidence continue offline; outbox syncs on reconnect (§23).
- Bounded queues give measurable `queue_depth / dropped_frames / frame_age` metrics (§10, §25) and overload behavior (drop old, not grow latency).
- Separate processes allow CPU/OpenVINO/CUDA profiles without single-env accelerator conflicts.

### Negative / Accepted Complexity
- Multi-process needs supervisor (Compose `restart: unless-stopped`, healthchecks); not a single `uvicorn` process like prototype.
- Frame queues are in-memory (lost on worker crash) — accepted; events/evidence are durable via PG outbox, frames are "stale anyway" per §5.

## Alternatives Considered

| Alt | Why rejected |
|-----|--------------|
| Single-process threaded pipeline (prototype) | Cannot isolate GPU/CPU runtimes; no transactional outbox isolation; violates §6 "API process must not execute permanent stream-processing loops" |
| Microservices + Kafka/Redis Streams for frames | Spec-explicitly rejects; frames are high-volume stale; would add latency |
| Kubernetes at Phase 1 | Premature per §6; defer until single-node soak proves |
| SQLite + aiosqlite | Spec requires PostgreSQL transactional outbox + durable jobs; SQLite lacks `SELECT … FOR UPDATE SKIP LOCKED` job leases at scale |

## Validation

- ADR review: Check queue metrics, outbox atomicity, and worker separation at Phase 3 E2E slice gate ("One actual video must create one persisted event").
- Chaos test §26: kill `camera worker`, `database restart`, `storage outage` — workers must recover with bounded retry.

## Replacement Strategy

Scale-out path after single-edge soak (§6): extract `camera worker` to N replicas keyed by `camera_id` + `stream_epoch`, shard by PG advisory locks; add `mediamtx` cluster behind LB; keep transactional outbox as single PG.

---

*Evidence:* `docs/research/version-evidence.md:8`, `docs/research/technology-comparison.md:1`, spec §6 diagram.
