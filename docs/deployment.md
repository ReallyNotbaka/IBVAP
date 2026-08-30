# IBVAP Deployment — Phase 8 (Stubs, pending benchmarks)

**Status:** Draft — CPU profile validated, OpenVINO/CUDA profiles documented but not benchmarked on target hardware.

## Profiles (compose.yaml)

- `dev` — FastAPI + Postgres 17 + MediaMTX 1.20.1 + Vite dev. `docker compose --profile dev up --build`
- `cpu` — Production CPU (ORT CPU). Same as dev but without Vite.
- `openvino` — Add `openvino==2026.3.1` extra, image `FROM openvino/ubuntu22_runtime:2026.3.1` (pending build test)
- `cuda` — `onnxruntime-gpu==1.29.0`, base `nvidia/cuda:12.2-runtime`, TensorRT 11.2.1 (pending GPU host)
- `observability` — OTEL collector + Prometheus + Grafana (optional)

All images are non-root, multi-stage, pinned digests.

## CPU degradation order (spec 28)

1. Lower analytics FPS per camera (fair share, Critical keeps quota)
2. Lower detector input within validated 320..640
3. Disable experimental (night enhance, face embed)
4. Preserve human/vehicle intrusion + health + outbox
5. Surface `system.degraded` via WS + health banner — never silent fallback.

## Install / Offline

```bash
uv sync --frozen
uv run alembic upgrade head
docker compose --profile dev up
```

Offline: `uv sync --frozen` uses committed `uv.lock`; frontend `npm ci --legacy-peer-deps` uses `package-lock.json`.

## Backup / Restore / Upgrade

- PG `pg_dump --format=custom` nightly via `durable_jobs` (pending)
- Restore: `pg_restore` + `alembic upgrade head`
- Upgrade: `uv lock --upgrade` + `alembic upgrade head` + rolling compose

## Remaining (Phase 8 exit)

- [ ] OpenVINO and CUDA benchmark evidence on Intel i5 / RTX 4060
- [ ] 24h soak + chaos (worker kill, DB restart, storage outage) logs
- [ ] SBOM `uv export --format cyclonedx1.5` + `npm sbom` committed
- [ ] Container scan (trivy) + license inventory
