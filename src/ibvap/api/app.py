"""FastAPI app factory - IBVAP Phase 1."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ibvap.api.routes.cameras import router as cameras_router
from ibvap.api.routes.events import router as events_router
from ibvap.api.routes.health import router as health_router
from ibvap.api.routes.models import router as models_router
from ibvap.api.routes.sites import router as sites_router
from ibvap.api.routes.uploads import router as uploads_router
from ibvap.api.routes.watchlist import router as watchlist_router
from ibvap.api.routes.ws import router as ws_router
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
    def _http_exception_envelope(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail  # type: ignore[attr-defined]
        # derive machine-readable code
        if isinstance(detail, dict) and "code" in detail:
            code = str(detail["code"])
        else:
            _code_map = {
                400: "bad_request",
                401: "unauthorized",
                403: "forbidden",
                404: "not_found",
                409: "conflict",
                413: "payload_too_large",
                422: "unprocessable_entity",
                500: "internal_error",
            }
            code = _code_map.get(exc.status_code, f"http_{exc.status_code}")  # type: ignore[attr-defined]
        _title_map = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            413: "Payload Too Large",
            422: "Unprocessable Entity",
            500: "Internal Server Error",
        }
        title = _title_map.get(exc.status_code, f"HTTP {exc.status_code}")  # type: ignore[attr-defined]
        return JSONResponse(
            status_code=exc.status_code,  # type: ignore[attr-defined]
            content={
                "type": "about:blank",
                "title": title,
                "status": exc.status_code,  # type: ignore[attr-defined]
                "detail": detail,
                "code": code,
                "correlation_id": request.headers.get("x-correlation-id", ""),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # type: ignore[no-untyped-def]
        return _http_exception_envelope(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # type: ignore[no-untyped-def]
        if isinstance(exc, StarletteHTTPException):
            return _http_exception_envelope(request, exc)
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
    app.include_router(cameras_router)
    app.include_router(models_router)
    app.include_router(sites_router)
    app.include_router(uploads_router)
    app.include_router(events_router)
    app.include_router(ws_router)
    app.include_router(watchlist_router)

    # optional frontend mount - existence checked at runtime (Phase 7 will always mount)
    try:
        from pathlib import Path
        from typing import Any

        from fastapi.staticfiles import StaticFiles
        from starlette.exceptions import HTTPException

        dist = Path("frontend/dist")
        if dist.exists() and (dist / "index.html").exists():

            class SPAStaticFiles(StaticFiles):
                async def get_response(self, path: str, scope: Any) -> Any:
                    try:
                        response = await super().get_response(path, scope)
                    except HTTPException as ex:
                        if ex.status_code == 404 and not Path(path).suffix:
                            response = await super().get_response("index.html", scope)
                        else:
                            raise
                    if path in {"", "index.html"} or not Path(path).suffix:
                        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                        response.headers["Pragma"] = "no-cache"
                        response.headers["Expires"] = "0"
                    return response

            # mount after API routes so /api/* takes precedence
            app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")
    except Exception:
        logging.getLogger(__name__).warning("Frontend assets were not mounted; build output is missing or invalid.", exc_info=True)


    return app


app = create_app()
