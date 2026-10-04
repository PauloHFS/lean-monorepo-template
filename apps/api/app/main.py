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
from app.core.logging import get_logger
from app.core.middleware import SecurityHeadersMiddleware
from app.core.observability import setup_observability, setup_sentry
from app.db.session import engine
from app.jobs.app import app as procrastinate_app

log = get_logger("api.main")

# Anchor relativo a este arquivo: apps/api/app/main.py -> apps/api/app -> apps/api
# -> apps -> <repo root> -> + apps/web/dist
_DEFAULT_SPA_DIST = (
    Path(__file__).resolve().parent.parent.parent.parent / "apps" / "web" / "dist"
)
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
    async with procrastinate_app.open_async():
        yield

    await engine.dispose()
    log.info("API encerrada")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Observability — vendor-agnostic no app. Setar OTEL_EXPORTER_OTLP_ENDPOINT
# (e opcionalmente SENTRY_DSN) habilita tracing + error tracking.
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
async def favicon():
    f = SPA_DIST / "favicon.ico"
    if f.exists():
        return FileResponse(f)
    return JSONResponse(status_code=404, content={"detail": "not found"})


if SPA_DIST.exists():
    assets_dir = SPA_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = SPA_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"detail": "front não buildado. Rode `just web-build`"},
        )
else:
    log.warning("SPA dist não encontrado em %s — fallback SPA desativado", SPA_DIST)


# -----------------------------------------------------------------------------
# Erros não tratados
# -----------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):  # noqa: ARG001
    log.exception("unhandled", path=str(request.url))
    return JSONResponse(status_code=500, content={"detail": "internal error"})