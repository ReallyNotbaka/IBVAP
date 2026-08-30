# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# -- deps
FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# -- build
FROM deps AS build
COPY src ./src
COPY README.md alembic.ini migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# -- runtime (cpu)
FROM python:3.12-slim-bookworm AS runtime
RUN useradd -m -u 10001 ibvap && mkdir -p /app/data/logs /app/data/frames && chown -R ibvap:ibvap /app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY --from=build /app/migrations /app/migrations
COPY --from=build /app/alembic.ini /app/alembic.ini
COPY --from=build /app/config /app/config
# frontend will be built separately and copied in prod
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src"
USER ibvap
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').read() else 1)"
CMD ["uvicorn", "ibvap.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
