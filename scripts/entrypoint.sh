#!/usr/bin/env bash
# =============================================================================
# Entry point único: decide se o container roda a API ou o worker
# conforme o argumento recebido. Roda migrations antes de subir.
# =============================================================================
set -euo pipefail

ROLE="${1:-api}"   # api | worker

# Espera Postgres se a DSN estiver apontando para um host DNS
if [[ -n "${POSTGRES_HOST:-}" ]]; then
  echo "[entrypoint] Aguardando Postgres em ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
  for i in {1..60}; do
    if (echo > "/dev/tcp/${POSTGRES_HOST}/${POSTGRES_PORT:-5432}") >/dev/null 2>&1; then
      echo "[entrypoint] Postgres reachable."
      break
    fi
    sleep 1
  done
fi

# Roda migrations (worker também precisa do schema em dia)
echo "[entrypoint] Rodando migrations (alembic upgrade head)..."
cd /app/apps/api
alembic upgrade head

case "$ROLE" in
  api)
    echo "[entrypoint] Subindo uvicorn..."
    exec uvicorn app.main:app \
      --host "${API_HOST:-0.0.0.0}" \
      --port "${API_PORT:-8000}" \
      --proxy-headers \
      --forwarded-allow-ips="*"
    ;;
  worker)
    echo "[entrypoint] Subindo worker (Procrastinate)..."
    exec python -m app.jobs.runner
    ;;
  *)
    echo "[entrypoint] Role inválida: '$ROLE' (use 'api' ou 'worker')" >&2
    exit 2
    ;;
esac
