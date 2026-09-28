"""FastAPI app factory - IBVAP Phase 1."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ibvap.api.routes.anpr import router as anpr_router
from ibvap.api.routes.cameras import router as cameras_router
from ibvap.api.routes.events import router as events_router
from ibvap.api.routes.evidence import router as evidence_router
from ibvap.api.routes.health import router as health_router
from ibvap.api.routes.models import router as models_router
from ibvap.api.routes.settings import router as settings_router
from ibvap.api.routes.sites import router as sites_router
from ibvap.api.routes.tactical import router as tactical_router
from ibvap.api.routes.uploads import router as uploads_router
from ibvap.api.routes.watchlist import router as watchlist_router
from ibvap.api.routes.ws import router as ws_router
from ibvap.config import Settings
from ibvap.logging_setup import setup_logging

# Hoisted error-envelope maps (avoid per-exception dict allocations).
_CODE_MAP: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    422: "unprocessable_entity",
    500: "internal_error",
}
_TITLE_MAP: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Task 5: honor the injected cfg (placed on app.state by create_app) so
    # operator/test overrides are respected instead of rebuilt from env.
    settings = getattr(app.state, "settings", None) or Settings()
    app.state.settings = settings
    setup_logging(settings.app.log_level, settings.app.log_dir)
    # Warm the shared YOLO session now (~1s model load + first GPU
    # inference): the first camera then connects fast instead of stalling
    # its worker. Blocking IO stays off the event loop.
    # Task 5: warmup must never take the API down — try/log-continue.
    try:
        from ibvap.core.dispatcher import load_settings
        from ibvap.core.model_manager import warmup_shared_detector
        from ibvap.services.persistence import init_persistence

        load_settings()
        await asyncio.to_thread(warmup_shared_detector)
        await init_persistence(settings)
    except Exception:
        logging.getLogger(__name__).warning(
            "startup warmup incomplete; continuing without preloaded state",
            exc_info=True,
        )
    yield
    # Task 5: shutdown cleanup — stop camera workers, then release the DB engine.
    try:
        from ibvap.db import dispose_engine
        from ibvap.services.stream_worker import _CAMERAS, _stop_worker

        for cam_id in list(_CAMERAS):
            try:
                _stop_worker(cam_id)
            except Exception:
                logging.getLogger(__name__).warning("worker stop failed", extra={"camera_id": cam_id}, exc_info=True)
        await dispose_engine()
    except Exception:
        logging.getLogger(__name__).warning("shutdown cleanup incomplete", exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    app = FastAPI(
        title="IBVAP — Intelligent Border Video Analytics Platform",
        version=cfg.app.version,
        description="Software-defined border video analytics (Phase 1 foundation)",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    # CORS - strict allowlist, not "*" (threat-model T-01 fix)
    # Task 1 P0: X-API-Token allowed so browser clients can send the mutating-route guard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.app.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID", "X-API-Token"],
    )
    # Compress JSON/MJPEG-manifest payloads >=1KB (no new deps; starlette built-in).
    # Exclude multipart streams from GZip compression to avoid buffering/latency overhead.
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

    app.add_middleware(
        GZipMiddleware,
        minimum_size=1024,
        exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + ("multipart/*", "multipart/x-mixed-replace"),
    )

    # problem-details error envelope
    # Canonical wire shape for failures: HTTP status + body
    # {"detail": {"code": "<machine_code>", "message": "<human message>"}}
    # wrapped in RFC 7807 problem-details (type/title/status/code/correlation_id).
    def _sanitize_for_json(value: Any) -> Any:
        # Task 5 fix-round 1: validation errors can carry non-finite floats
        # (inf/nan inputs) in `input`/`ctx` — stdlib json cannot serialize
        # those, which turned 422s into 500s. Stringify them instead.
        if isinstance(value, float):
            if value != value:
                return "NaN"
            if value == float("inf"):
                return "Infinity"
            if value == float("-inf"):
                return "-Infinity"
            return value
        if isinstance(value, dict):
            return {k: _sanitize_for_json(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_sanitize_for_json(v) for v in value]
        return value

    def _http_exception_envelope(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail  # type: ignore[attr-defined]
        # derive machine-readable code (detail is typed str|None upstream but
        # routes raise dicts; cast after the isinstance check, no runtime effect)
        code = (
            str(cast("dict[str, Any]", detail)["code"])
            if isinstance(detail, dict) and "code" in detail
            else _CODE_MAP.get(exc.status_code, f"http_{exc.status_code}")
        )  # type: ignore[attr-defined]
        title = _TITLE_MAP.get(exc.status_code, f"HTTP {exc.status_code}")  # type: ignore[attr-defined]
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

    @app.exception_handler(RequestValidationError)
    async def _validation_exception(request: Request, exc: RequestValidationError) -> JSONResponse:  # type: ignore[no-untyped-def]
        # Task 5 fix-round 1: body/query/path validation failures are 422s with
        # the canonical {"code","message"} detail — never a 500 from unserializable input.
        raw_errors = exc.errors()
        errors = _sanitize_for_json(raw_errors)
        first = raw_errors[0] if raw_errors else {}
        loc = ".".join(str(p) for p in first.get("loc", ())) if isinstance(first, dict) else ""
        msg = first.get("msg", "Validation failed") if isinstance(first, dict) else "Validation failed"
        message = f"{loc}: {msg}" if loc else str(msg)
        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": {"code": "validation_error", "message": message},
                "code": "validation_error",
                "errors": errors,
                "correlation_id": request.headers.get("x-correlation-id", ""),
            },
        )

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
    app.include_router(tactical_router)
    app.include_router(anpr_router)
    app.include_router(evidence_router)
    app.include_router(settings_router)

    # optional frontend mount - existence checked at runtime (Phase 7 will always mount)
    try:
        from pathlib import Path

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
                    suffix = Path(path).suffix
                    if path in {"", "index.html"} or not suffix:
                        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                        response.headers["Pragma"] = "no-cache"
                        response.headers["Expires"] = "0"
                    elif suffix in {".js", ".css", ".woff2", ".png", ".jpg", ".svg"}:
                        # Immutable hashed build assets: safe long cache.
                        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
                    return response

            # mount after API routes so /api/* takes precedence
            app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")
    except Exception:
        logging.getLogger(__name__).warning(
            "Frontend assets were not mounted; build output is missing or invalid.", exc_info=True
        )

    return app


# Task 5: no import-time create_app() — serve via the factory
# (uvicorn ibvap.api.app:create_app --factory) so Settings/lang/env are read
# at serve time, not import time.
