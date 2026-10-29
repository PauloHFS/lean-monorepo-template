"""FastAPI entrypoint.

1. /api/v1/* — REST
2. /assets/* e /favicon.ico — build estático do front
3. SPA fallback: qualquer rota não-API serve index.html

A ordem é importante: rotas registradas têm prioridade sobre o fallback catch-all.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.core.config import settings
from app.core.jobs import JobRateLimitExceeded
from app.core.logging import get_logger
from app.core.middleware import SecurityHeadersMiddleware, TraceIdMiddleware
from app.core.observability import (
    setup_observability,
    setup_sentry,
    shutdown_tracing,
)
from app.db.session import engine
from app.jobs.app import app as procrastinate_app
from app.permissions import PermissionDenied
from app.services.errors import NotFoundError

log = get_logger("api.main")

# Anchor relativo a este arquivo: apps/api/app/main.py -> apps/api/app -> apps/api
# -> apps -> <repo root> -> + apps/web/dist
_DEFAULT_SPA_DIST = Path(__file__).resolve().parent.parent.parent.parent / "apps" / "web" / "dist"
SPA_DIST = Path(os.environ.get("SPA_DIST_PATH", str(_DEFAULT_SPA_DIST))).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        log.info("DB ok")
    except Exception:
        log.exception("Falha ao conectar no Postgres")
        raise

    # Abre o pool do Procrastinate (usado por defer_async nos endpoints/CLI).
    # O import de `app.jobs.app` também registra as tasks do app.
    try:
        async with procrastinate_app.open_async():
            yield
    finally:
        shutdown_tracing()
        await engine.dispose()
        log.info("API encerrada")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    # Em prod os docs/OpenAPI expõem o mapa de rotas a anônimos; desliga.
    docs_url=None if settings.is_prod else "/api/docs",
    redoc_url=None if settings.is_prod else "/api/redoc",
    openapi_url=None if settings.is_prod else "/api/openapi.json",
)

# Observability — vendor-agnostic no app. Setar OTEL_EXPORTER_OTLP_ENDPOINT
# (e opcionalmente SENTRY_DSN) habilita tracing + error tracking.
# TraceIdMiddleware entra ANTES do instrumentor para ficar dentro do span.
app.add_middleware(TraceIdMiddleware)
setup_sentry()
setup_observability(app)

# CORS:宽松 para dev do Vite; em prod o front é mesmo host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin] if not settings.is_prod else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


app.include_router(api_router, prefix="/api/v1")


# -----------------------------------------------------------------------------
# SPA (front estático)
# -----------------------------------------------------------------------------


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    """Serve o favicon que existir no build (o Vite copia `public/` para `dist/`)."""
    for name in ("favicon.svg", "favicon.ico"):
        f = SPA_DIST / name
        if f.exists():
            return FileResponse(f)
    return JSONResponse(status_code=404, content={"detail": "not found"})


if SPA_DIST.exists():
    assets_dir = SPA_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        index = SPA_DIST / "index.html"
        if index.exists():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            status_code=503,
            content={"detail": "front não buildado. Rode `just web-build`"},
        )
else:
    log.warning("SPA dist não encontrado em %s — fallback SPA desativado", SPA_DIST)


# -----------------------------------------------------------------------------
# Erros não tratados
# -----------------------------------------------------------------------------
@app.exception_handler(PermissionDenied)
async def permission_denied_handler(request: Request, exc: PermissionDenied):
    log.warning(
        "permission.denied", action=exc.action.value, resource=exc.resource.value, reason=exc.reason
    )
    return JSONResponse(status_code=403, content={"detail": "forbidden"})


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": "not found"})


@app.exception_handler(JobRateLimitExceeded)
async def job_rate_limit_exceeded(request: Request, exc: JobRateLimitExceeded):  # noqa: ARG001
    """Rate limit de job enfileirado: 429, não 500."""
    log.warning("job rate limit excedido", kind=exc.kind, key=exc.key)
    return JSONResponse(
        status_code=429,
        content={"detail": "job rate limit exceeded"},
        headers={"Retry-After": str(exc.window_s)},
    )


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):  # noqa: ARG001
    log.exception("unhandled", path=str(request.url))
    return JSONResponse(status_code=500, content={"detail": "internal error"})
