# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# -- deps (cached unless manifests change)
FROM base AS deps
COPY --link pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# -- build (project sources last so edits don't invalidate the deps layer)
FROM deps AS build
COPY --link src ./src
COPY --link README.md ./README.md
COPY --link alembic.ini ./alembic.ini
COPY --link migrations ./migrations
COPY --link config ./config
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# -- runtime (cpu)
FROM python:3.12-slim-bookworm AS runtime
RUN useradd -m -u 10001 ibvap && mkdir -p /app/data/logs /app/data/frames && chown -R ibvap:ibvap /app
WORKDIR /app
COPY --link --from=build /app/.venv /app/.venv
COPY --link --from=build /app/src /app/src
COPY --link --from=build /app/migrations /app/migrations
COPY --link --from=build /app/alembic.ini /app/alembic.ini
COPY --link --from=build /app/config /app/config
# frontend will be built separately and copied in prod
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER ibvap
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=2).read() else 1)"
CMD ["uvicorn", "ibvap.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
