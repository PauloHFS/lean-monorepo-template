#!/usr/bin/env bash
# =============================================================================
# Restauração de um dump custom do Postgres (pg_restore).
#
# Uso: scripts/restore.sh <arquivo.dump> [--db NOME] [--dry-run] [--yes]
#
# Segurança:
#   - O banco de destino vem de --db ou POSTGRES_RESTORE_DB. Nunca é adivinhado.
#   - Sem --yes, pede confirmação interativa; sem TTY, recusa.
#   - O dump é validado com `pg_restore --list` antes de qualquer escrita e
#     NUNCA é apagado.
# =============================================================================
set -euo pipefail

usage() {
  cat <<'EOF'
Uso: scripts/restore.sh <arquivo.dump> [opções]

Opções:
  --db NOME        banco de destino (ou POSTGRES_RESTORE_DB)
  --dry-run        só lista as entradas do dump; não toca no banco
  --yes, -y        não pede confirmação (modo não interativo)
  -h, --help       mostra esta ajuda

Conexão (env ou .env): POSTGRES_HOST, POSTGRES_PORT (5432),
  POSTGRES_USER, POSTGRES_PASSWORD, ENV_FILE (default: .env).

Exemplos:
  # inspecionar o dump sem restaurar
  ./scripts/restore.sh /tmp/lean-monorepo-backups/app_20240101T033000Z.dump --dry-run

  # restaurar num banco de teste, sem prompt
  ./scripts/restore.sh /tmp/lean-monorepo-backups/app_20240101T033000Z.dump \
    --db app_restore_test --yes

  # restaurar pedindo confirmação interativa
  POSTGRES_RESTORE_DB=app_restore_test ./scripts/restore.sh app.dump
EOF
}

DUMP=""
TARGET_DB=""
DRY_RUN=0
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --db)
      [[ $# -ge 2 ]] || { echo "[restore] ERRO: --db exige um valor" >&2; exit 2; }
      TARGET_DB="$2"
      shift 2
      ;;
    --db=*)
      TARGET_DB="${1#--db=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --yes | -y)
      ASSUME_YES=1
      shift
      ;;
    --)
      shift
      if [[ $# -gt 0 && -z "$DUMP" ]]; then
        DUMP="$1"
        shift
      fi
      ;;
    -*)
      echo "[restore] ERRO: opção desconhecida: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "$DUMP" ]]; then
        echo "[restore] ERRO: mais de um arquivo informado: $1" >&2
        exit 2
      fi
      DUMP="$1"
      shift
      ;;
  esac
done

if [[ -z "$DUMP" ]]; then
  echo "[restore] ERRO: informe o arquivo .dump" >&2
  usage >&2
  exit 2
fi
if [[ ! -f "$DUMP" ]]; then
  echo "[restore] ERRO: arquivo não encontrado: $DUMP" >&2
  exit 1
fi
if [[ ! -r "$DUMP" ]]; then
  echo "[restore] ERRO: arquivo sem permissão de leitura: $DUMP" >&2
  exit 1
fi
if ! command -v pg_restore >/dev/null 2>&1; then
  echo "[restore] ERRO: pg_restore não encontrado no PATH" >&2
  exit 1
fi

# Carrega .env se existir (depois do --help, para a ajuda não exigir ambiente).
ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi

# Valida o dump antes de qualquer coisa.
if ! LIST="$(pg_restore --list "$DUMP")"; then
  echo "[restore] ERRO: pg_restore --list falhou; dump inválido/ilegível: $DUMP" >&2
  exit 1
fi
ENTRY_COUNT="$(printf '%s\n' "$LIST" | grep -cE '^[0-9]+;' || true)"
ENTRY_COUNT="${ENTRY_COUNT:-0}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[restore] dry-run: ${ENTRY_COUNT} entradas em $(basename "$DUMP"); banco não será tocado"
  printf '%s\n' "$LIST"
  exit 0
fi

TARGET_DB="${TARGET_DB:-${POSTGRES_RESTORE_DB:-}}"
if [[ -z "$TARGET_DB" ]]; then
  echo "[restore] ERRO: informe o banco de destino com --db NOME ou POSTGRES_RESTORE_DB." >&2
  echo "[restore] Recusando adivinhar (proteção contra restaurar no banco errado)." >&2
  exit 1
fi

: "${POSTGRES_HOST:?POSTGRES_HOST não definido (exporte ou use .env)}"
: "${POSTGRES_USER:?POSTGRES_USER não definido (exporte ou use .env)}"

if [[ -n "${POSTGRES_DB:-}" && "$TARGET_DB" == "$POSTGRES_DB" ]]; then
  echo "[restore] ATENÇÃO: '$TARGET_DB' é o mesmo POSTGRES_DB de onde o backup saiu." >&2
fi

if [[ "$ASSUME_YES" -ne 1 ]]; then
  if [[ ! -t 0 ]]; then
    echo "[restore] ERRO: entrada não interativa; use --yes para confirmar." >&2
    exit 1
  fi
  printf "[restore] Isso APAGA/recria objetos em '%s'. Digite 'yes' para continuar: " "$TARGET_DB"
  read -r answer
  if [[ "$answer" != "yes" ]]; then
    echo "[restore] abortado." >&2
    exit 1
  fi
fi

echo "[restore] restaurando $(basename "$DUMP") em '$TARGET_DB' (${ENTRY_COUNT} entradas)"
PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_restore \
  --host "$POSTGRES_HOST" \
  --port "${POSTGRES_PORT:-5432}" \
  --username "$POSTGRES_USER" \
  --dbname "$TARGET_DB" \
  --clean --if-exists \
  --no-owner --no-privileges \
  "$DUMP"

echo "[restore] ok: ${ENTRY_COUNT} entradas restauradas em '$TARGET_DB' (dump preservado em $DUMP)"
