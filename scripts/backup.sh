#!/usr/bin/env bash
# =============================================================================
# Backup lógico do Postgres -> arquivo .dump.gz -> Cloudflare R2 via rclone.
# Uso: ./scripts/backup.sh
# Cron (diário às 03:30): 30 3 * * * /opt/lean-monorepo/scripts/backup.sh
# =============================================================================
set -euo pipefail

# Carrega .env se existir
ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi

: "${POSTGRES_HOST:?POSTGRES_HOST não definido}"
: "${POSTGRES_DB:?POSTGRES_DB não definido}"
: "${POSTGRES_USER:?POSTGRES_USER não definido}"
: "${RCLONE_REMOTE_NAME:=r2}"
: "${RCLONE_BUCKET:?RCLONE_BUCKET não definido}"
: "${BACKUP_KEEP_DAYS:=14}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_DIR:-/tmp/lean-monorepo-backups}"
OUT_FILE="${OUT_DIR}/${POSTGRES_DB}_${TS}.dump"
KEEP_DAYS="${BACKUP_KEEP_DAYS}"

mkdir -p "$OUT_DIR"

echo "[backup] gerando $OUT_FILE (formato custom, comprimido)"
PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
  -h "$POSTGRES_HOST" \
  -p "${POSTGRES_PORT:-5432}" \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -Fc \
  -Z 9 \
  --no-owner \
  --no-privileges \
  -f "$OUT_FILE"

# Checagem de sanidade: o arquivo não pode estar zerado
if [[ ! -s "$OUT_FILE" ]]; then
  echo "[backup] ERRO: dump vazio" >&2
  exit 1
fi

REMOTE_PATH="${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}/db/$(basename "$OUT_FILE")"
echo "[backup] enviando para $REMOTE_PATH"
rclone copyto "$OUT_FILE" "$REMOTE_PATH" --progress --s3-no-check-bucket

# Limpeza local
rm -f "$OUT_FILE"

# Limpeza remota: apaga dumps com mais de KEEP_DAYS dias
echo "[backup] aplicando retenção (${KEEP_DAYS} dias) no R2"
rclone delete "${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}/db" \
  --min-age "${KEEP_DAYS}d" \
  --include "${POSTGRES_DB}_*.dump" \
  || true

echo "[backup] ok."
