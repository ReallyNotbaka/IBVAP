# IBVAP — Intelligent Border Video Analytics Platform

Software-defined video analytics that turns ordinary IP cameras and smartphone IP-webcam feeds into an intelligent surveillance network — no proprietary smart-camera hardware required.

## Install (uv only — no pip, no requirements.txt)

```bash
# requires Python 3.12 and uv 0.12+
uv sync --frozen
uv run ibvap --help
```

ANPR uses PaddleOCR on `gpu:0` by default. Install the matching PaddlePaddle GPU
wheel for the host from the official PaddlePaddle instructions before starting
the backend; set `IBVAP_ANPR_DEVICE=cpu` only for a deliberate CPU fallback.

## Dev

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q
```

## Compose (dev)

```bash
docker compose -f compose.yaml --profile dev up --build
# or
docker compose --profile dev up
```

Frontend dev:

```bash
cd frontend
npm install
npm run dev
```

## Structure

- `src/ibvap/` — Python backend (FastAPI, SQLAlchemy async, Alembic, PyAV pipeline)
- `migrations/` — Alembic migrations (PostgreSQL)
- `frontend/` — React 19 + Vite + TypeScript strict + Tailwind + TanStack Query
- `compose.yaml` — dev/cpu/openvino/cuda/observability profiles
- `docs/` — Phase 0 research, ADRs, threat model, traceability

## License / YOLO26 gate

YOLO26 (Ultralytics) is AGPL-3.0. The product does **not** bundle YOLO weights until an Enterprise grant is recorded (see `docs/adr/0004-detector-and-licensing.md`). A permissive RF-DETR alternative is documented.
