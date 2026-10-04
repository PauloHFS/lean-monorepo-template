#!/usr/bin/env bash
# Verifica se `apps/web/src/api/schema.d.ts` está em sync com o backend.
# Falha com exit 1 se drift; o dev roda `just web-types` pra sincronizar.
set -euo pipefail

# Encontra repo root (funciona fora ou dentro de git)
if git rev-parse --show-toplevel >/dev/null 2>&1; then
    cd "$(git rev-parse --show-toplevel)"
else
    cd "$(dirname "$0")/.."
fi

# Garante que o venv existe e tem deps
if [[ ! -d apps/api/.venv ]]; then
    echo "apps/api/.venv não existe; rode: just api-install"
    exit 1
fi

# Gera OpenAPI temporário e compara
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
(cd apps/api && PYTHONPATH=apps/api .venv/bin/python -m app.cli dump-openapi) > "$TMP" 2>/dev/null

if apps/web/node_modules/.bin/openapi-typescript "$TMP" -o /tmp/schema-drift.d.ts >/dev/null 2>&1; then
    if ! diff -q apps/web/src/api/schema.d.ts /tmp/schema-drift.d.ts >/dev/null 2>&1; then
        echo "schema.d.ts desatualizado em relação ao backend."
        echo "Rode: just web-types"
        rm -f /tmp/schema-drift.d.ts
        exit 1
    fi
    rm -f /tmp/schema-drift.d.ts
else
    echo "Falha ao regenerar schema para checagem."
    exit 1
fi