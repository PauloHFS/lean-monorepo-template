# =============================================================================
# Multi-stage:
#   1) build-web: Node faz o build do Vite → apps/web/dist
#   2) base (final): Python + código + dist do front, dois entrypoints
# =============================================================================

# ---- Stage 1: front ---------------------------------------------------------
FROM node:20-alpine AS build-web
WORKDIR /web
COPY apps/web/package.json ./
RUN npm install --no-audit --no-fund
COPY apps/web ./
RUN npm run build

# ---- Stage 2: api+worker ----------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY apps/api /app/apps/api
COPY scripts /app/scripts
# Copia o build do front (Stage 1)
COPY --from=build-web /web/dist /app/apps/web/dist

RUN chmod +x /app/scripts/entrypoint.sh

ENV PYTHONPATH=/app/apps/api

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${API_PORT:-8000}/api/v1/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-lc", "/app/scripts/entrypoint.sh api"]
