# =============================================================================
# Multi-stage:
#   1) build-web: Node faz o build do Vite → apps/web/dist
#   2) base (final): Python + código + dist do front, dois entrypoints
# =============================================================================

# ---- Stage 1: front ---------------------------------------------------------
FROM node:20-alpine AS build-web
WORKDIR /web
# browsers do Playwright nao sao necessarios no build do Vite
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

# ---- Stage 2: api+worker ----------------------------------------------------
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/pyproject.toml apps/api/uv.lock /app/apps/api/
RUN cd /app/apps/api && uv sync --frozen --no-dev --python /usr/local/bin/python3.12

COPY apps/api /app/apps/api
COPY scripts /app/scripts
# Copia o build do front (Stage 1)
COPY --from=build-web /web/dist /app/apps/web/dist

RUN chmod +x /app/scripts/entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/apps/api

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${API_PORT:-8000}/api/v1/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "/app/scripts/entrypoint.sh api"]
