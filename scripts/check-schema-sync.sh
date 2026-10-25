#!/usr/bin/env bash
# Verifica se `apps/web/src/api/schema.d.ts` está em sync com o backend.
# Falha com exit 1 se drift; o dev roda `just web-types` pra sincronizar.
# Também aplica o gate semântico: nenhuma resposta de rota pode ficar sem tipo
# útil (`Record<string, never>` = dict sem properties; `unknown` = rota sem
# response_model declarado).
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
TMP_DTS="$(mktemp)"
trap 'rm -f "$TMP" "$TMP_DTS"' EXIT
(cd apps/api && uv run python -m app.cli dump-openapi) > "$TMP" 2>/dev/null

if ! apps/web/node_modules/.bin/openapi-typescript "$TMP" -o "$TMP_DTS" >/dev/null 2>&1; then
    echo "Falha ao regenerar schema para checagem."
    exit 1
fi

if ! diff -q apps/web/src/api/schema.d.ts "$TMP_DTS" >/dev/null 2>&1; then
    echo "schema.d.ts desatualizado em relação ao backend."
    echo "Rode: just web-types"
    exit 1
fi

# Gate semântico: toda resposta de rota precisa referenciar um schema útil.
if grep -qE '"application/json":[[:space:]]+(Record<string, never>|unknown)' "$TMP_DTS"; then
    echo "Resposta de rota sem contrato tipado:"
    grep -nE '"application/json":[[:space:]]+(Record<string, never>|unknown)' "$TMP_DTS"
    echo "Modele a resposta com Pydantic (response_model=...) e rode: just web-types"
    exit 1
fi
