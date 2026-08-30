"""FastAPI app factory - IBVAP Phase 1."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ibvap.api.routes.health import router as health_router
from ibvap.config import Settings
from ibvap.logging_setup import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = Settings()
    setup_logging(settings.app.log_level, settings.app.log_dir)
    app.state.settings = settings
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    app = FastAPI(
        title="IBVAP — Intelligent Border Video Analytics Platform",
        version=cfg.app.version,
        description="Software-defined border video analytics (Phase 1 foundation)",
        lifespan=lifespan,
    )

    # CORS - strict allowlist, not "*" (threat-model T-01 fix)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.app.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID"],
    )

    # problem-details error envelope
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # type: ignore[no-untyped-def]
        return JSONResponse(
            status_code=500,
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "Unexpected error",
                "code": "internal_error",
                "correlation_id": request.headers.get("x-correlation-id", ""),
            },
        )

    app.include_router(health_router)

    # optional frontend mount - existence checked at runtime (Phase 7 will always mount)
    try:
        from pathlib import Path

        from fastapi.staticfiles import StaticFiles

        dist = Path("frontend/dist")
        if dist.exists() and (dist / "index.html").exists():
            # mount after API routes so /api/* takes precedence
            app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    except Exception:
        pass

    return app


app = create_app()
