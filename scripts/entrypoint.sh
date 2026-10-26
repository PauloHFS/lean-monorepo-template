#!/usr/bin/env bash
# =============================================================================
# Entry point único dos containers do backend.
#
# Papéis:
#   migrate : roda `alembic upgrade head` uma vez e sai (exit 0)
#   api     : espera o Postgres e sobe o uvicorn
#   worker  : espera o Postgres e sobe o worker Procrastinate
#
# Migrations NÃO rodam em api/worker: o compose sobe um serviço `migrate`
# one-shot e api/worker dependem de `service_completed_successfully`, o que
# elimina a corrida de `alembic upgrade head` entre os dois containers.
#
# Portas: API_INTERNAL_PORT é a porta INTERNA do container (default 8000).
# API_PORT é a porta PUBLICADA no host, mapeada no docker-compose.yml. O
# HEALTHCHECK do Dockerfile deve usar a MESMA variável API_INTERNAL_PORT.
# =============================================================================
set -euo pipefail

# O `bash -lc` (login shell) executa /etc/profile, que reescreve o PATH e
# descarta o /opt/venv/bin do ENV da imagem → `alembic`/`uvicorn`/`python`
# somem e o container morre com exit 127. Garante o venv do uv aqui, para
# qualquer invocação (compose, `docker run`, k8s).
export PATH="/opt/venv/bin:${PATH}"

ROLE="${1:-api}"   # migrate | api | worker
PG_HOST="${POSTGRES_HOST:-}"
PG_PORT="${POSTGRES_PORT:-5432}"
WAIT_ATTEMPTS="${POSTGRES_WAIT_ATTEMPTS:-60}"
API_INTERNAL_PORT="${API_INTERNAL_PORT:-8000}"
# X-Forwarded-For só é confiado vindo do proxy (loopback por padrão). Sem
# isso qualquer cliente forja o IP e ganha um bucket novo de rate limit.
# O uvicorn lê esta variável; nunca use "*" em produção.
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1}"

# Probe usado para a espera. `pg_isready` é preferível (fala o protocolo do
# Postgres); sem o binário na imagem, cai no probe TCP via /dev/tcp.
if command -v pg_isready >/dev/null 2>&1; then
  PROBE_NAME="pg_isready"
  probe_postgres() { pg_isready -h "$PG_HOST" -p "$PG_PORT" >/dev/null 2>&1; }
else
  PROBE_NAME="TCP /dev/tcp"
  probe_postgres() { (echo > "/dev/tcp/${PG_HOST}/${PG_PORT}") >/dev/null 2>&1; }
fi

wait_for_postgres() {
  if [[ -z "$PG_HOST" ]]; then
    return 0
  fi

  echo "[entrypoint] Aguardando Postgres em ${PG_HOST}:${PG_PORT} (${PROBE_NAME})..."

  local attempt delay
  for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
    if probe_postgres; then
      echo "[entrypoint] Postgres pronto."
      return 0
    fi

    # Backoff: 1s no começo, 3s depois, teto de 5s.
    if ((attempt < 10)); then
      delay=1
    elif ((attempt < 30)); then
      delay=3
    else
      delay=5
    fi
    sleep "$delay"
  done

  echo "[entrypoint] ERRO: Postgres em ${PG_HOST}:${PG_PORT} não respondeu após ${WAIT_ATTEMPTS} tentativas (${PROBE_NAME})." >&2
  exit 1
}

wait_for_postgres

cd /app/apps/api

case "$ROLE" in
  migrate)
    echo "[entrypoint] Rodando migrations (alembic upgrade head) e saindo..."
    exec alembic upgrade head
    ;;
  api)
    echo "[entrypoint] Subindo uvicorn na porta interna ${API_INTERNAL_PORT}..."
    # --proxy-headers usa FORWARDED_ALLOW_IPS (exportado acima).
    exec uvicorn app.main:app \
      --host "${API_HOST:-0.0.0.0}" \
      --port "${API_INTERNAL_PORT}" \
      --proxy-headers
    ;;
  worker)
    echo "[entrypoint] Subindo worker (Procrastinate)..."
    exec python -m app.jobs.runner
    ;;
  *)
    echo "[entrypoint] Role inválida: '$ROLE' (use 'migrate', 'api' ou 'worker')" >&2
    exit 2
    ;;
esac
