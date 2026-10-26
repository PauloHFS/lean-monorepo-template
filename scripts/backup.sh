#!/usr/bin/env bash
# =============================================================================
# Backup lógico do Postgres -> dump em formato custom (comprimido).
#
# Uso: ./scripts/backup.sh [--help]
# Cron (diário às 03:30): 30 3 * * * /opt/lean-monorepo/scripts/backup.sh
#
# Modos:
#   RCLONE_BUCKET preenchido -> envia para r2:<bucket>/db/ e remove o dump local.
#   RCLONE_BUCKET vazio      -> modo local: NÃO envia nada e MANTÉM o dump
#                               (e o sidecar .sha256) em BACKUP_DIR.
#
# Variáveis:
#   POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER (obrigatórias)
#   POSTGRES_PASSWORD, POSTGRES_PORT (5432)
#   RCLONE_BUCKET (vazio = modo local), RCLONE_REMOTE_NAME (r2)
#   BACKUP_KEEP_DAYS (14), BACKUP_DIR (/tmp/lean-monorepo-backups)
#
# Sanidade: o dump só é considerado válido se `pg_restore --list` conseguir
# lê-lo. Em caso de falha, nada é enviado e nada é apagado.
# =============================================================================
set -euo pipefail

usage() {
  cat <<'EOF'
Uso: scripts/backup.sh [--help]

Gera um dump do Postgres em BACKUP_DIR e, se RCLONE_BUCKET estiver preenchido,
envia para r2:<bucket>/db/ e remove o dump local.

Com RCLONE_BUCKET vazio (modo local), nada é enviado e o dump permanece em
BACKUP_DIR junto do sidecar <arquivo>.dump.sha256.

Variáveis:
  POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER   obrigatórias
  POSTGRES_PASSWORD, POSTGRES_PORT            opcionais (5432)
  RCLONE_BUCKET                               vazio = modo local
  RCLONE_REMOTE_NAME                          default: r2
  BACKUP_KEEP_DAYS                            default: 14 (retenção remota)
  BACKUP_DIR                                  default: /tmp/lean-monorepo-backups
  ENV_FILE                                    default: .env

Exemplos:
  ./scripts/backup.sh
  RCLONE_BUCKET= ./scripts/backup.sh
  BACKUP_DIR=/var/backups/lean ./scripts/backup.sh --help
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  "") ;;
  *)
    echo "[backup] ERRO: argumento desconhecido: $1" >&2
    usage >&2
    exit 2
    ;;
esac

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
RCLONE_BUCKET="${RCLONE_BUCKET:-}"
: "${BACKUP_KEEP_DAYS:=14}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/lean-monorepo-backups}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TS}.dump"
KEEP_DAYS="${BACKUP_KEEP_DAYS}"

mkdir -p "$BACKUP_DIR"

# Evita execuções sobrepostas. flock não existe no macOS (dev): degrada para
# aviso em vez de quebrar o script. No Linux/cron a proteção é real.
exec 9>"${BACKUP_DIR}/.backup.lock"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then
    echo "[backup] outro backup em andamento; saindo."
    exit 0
  fi
else
  echo "[backup] AVISO: flock não encontrado (macOS?); seguindo sem lock" >&2
fi

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

# Sanidade: arquivo não vazio E legível pelo pg_restore (formato custom válido).
if [[ ! -s "$OUT_FILE" ]]; then
  echo "[backup] ERRO: dump vazio: $OUT_FILE" >&2
  exit 1
fi
if ! pg_restore --list "$OUT_FILE" >/dev/null; then
  echo "[backup] ERRO: dump ilegível (pg_restore --list falhou): $OUT_FILE" >&2
  exit 1
fi

# Checksum: sha256sum no Linux, shasum -a 256 no macOS.
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$OUT_FILE" >"${OUT_FILE}.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$OUT_FILE" >"${OUT_FILE}.sha256"
else
  echo "[backup] ERRO: sha256sum/shasum não encontrado" >&2
  exit 1
fi
echo "[backup] sha256: $(<"${OUT_FILE}.sha256")"

if [[ -n "$RCLONE_BUCKET" ]]; then
  REMOTE_PATH="${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}/db/$(basename "$OUT_FILE")"
  echo "[backup] enviando para $REMOTE_PATH"
  rclone copyto "$OUT_FILE" "$REMOTE_PATH" --progress --s3-no-check-bucket

  # Limpeza local só depois do upload bem-sucedido.
  rm -f "$OUT_FILE" "${OUT_FILE}.sha256"

  # Limpeza remota: apaga dumps com mais de KEEP_DAYS dias. Falha não é fatal,
  # mas precisa aparecer no log (antes falhava em silêncio).
  echo "[backup] aplicando retenção (${KEEP_DAYS} dias) em ${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}"
  if ! rclone delete "${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}/db" \
    --min-age "${KEEP_DAYS}d" \
    --include "${POSTGRES_DB}_*.dump"; then
    echo "[backup] AVISO: falha na retenção remota; dumps antigos podem sobrar" >&2
  fi
else
  echo "[backup] RCLONE_BUCKET vazio: modo local, nada enviado."
  echo "[backup] dump mantido em $OUT_FILE (+ $(basename "${OUT_FILE}.sha256"))"
fi

echo "[backup] ok."
