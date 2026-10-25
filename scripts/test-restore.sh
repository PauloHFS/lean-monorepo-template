#!/usr/bin/env bash
# =============================================================================
# Prova automatizada de restauração: backup local -> restore -> verificação.
#
# Uso: ./scripts/test-restore.sh [--help]
#
# Requer psql, pg_dump e pg_restore no PATH e POSTGRES_HOST, POSTGRES_PORT,
# POSTGRES_USER, POSTGRES_PASSWORD (POSTGRES_DB é opcional e só compõe o nome
# dos bancos temporários).
#
# Segurança: este script só cria/dropa bancos cujo nome contém "restore_test".
# Qualquer outro nome aborta antes de tocar no banco. Ele NUNCA usa o banco de
# produção como origem ou destino.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR=""
SRC_DB=""
DST_DB=""
RESULT="FAIL"

usage() {
  cat <<'EOF'
Uso: scripts/test-restore.sh [--help]

Fluxo:
  1. cria <POSTGRES_DB>_restore_test_src e <POSTGRES_DB>_restore_test_dst
  2. semeia a fonte com uma tabela de prova (PK, sequência, índice, 3 linhas)
  3. roda scripts/backup.sh em modo local (BACKUP_DIR temporário)
  4. roda scripts/restore.sh do dump para o banco alvo
  5. compara contagem e hash do conteúdo, e confere PK/índice/sequência
  6. imprime PASS/FAIL e remove os bancos e arquivos temporários

Pré-requisitos:
  psql, pg_dump, pg_restore no PATH
  POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD
  POSTGRES_DB (opcional; default: lean)

Exemplo:
  POSTGRES_HOST=localhost POSTGRES_PORT=5432 POSTGRES_USER=app \
    POSTGRES_PASSWORD=app ./scripts/test-restore.sh
EOF
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    echo "[test-restore] ERRO: argumento desconhecido: $1" >&2
    usage >&2
    exit 2
    ;;
esac

log() { echo "[test-restore] $*"; }
fail() {
  echo "[test-restore] ERRO: $*" >&2
  exit 1
}

# Carrega .env se existir.
ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi

missing=()
for bin in psql pg_dump pg_restore; do
  command -v "$bin" >/dev/null 2>&1 || missing+=("$bin")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "[test-restore] pré-requisitos ausentes: ${missing[*]}" >&2
  echo "[test-restore] instale o client do Postgres e garanta os binários no PATH." >&2
  exit 1
fi

[[ -n "${POSTGRES_HOST:-}" ]] || fail "POSTGRES_HOST não definido"
[[ -n "${POSTGRES_PORT:-}" ]] || fail "POSTGRES_PORT não definido"
[[ -n "${POSTGRES_USER:-}" ]] || fail "POSTGRES_USER não definido"
[[ -n "${POSTGRES_PASSWORD:-}" ]] || fail "POSTGRES_PASSWORD não definido"

BASE_DB="${POSTGRES_DB:-lean}"
case "$BASE_DB" in
  "" | *[!A-Za-z0-9_]*)
    fail "POSTGRES_DB inválido para compor nomes de banco: '$BASE_DB'"
    ;;
esac
SRC_DB="${BASE_DB}_restore_test_src"
DST_DB="${BASE_DB}_restore_test_dst"

export PGHOST="$POSTGRES_HOST"
export PGPORT="$POSTGRES_PORT"
export PGUSER="$POSTGRES_USER"
export PGPASSWORD="$POSTGRES_PASSWORD"

guard_db() {
  case "$1" in
    *restore_test*) : ;;
    *) fail "recusando operar no banco '$1' (nome sem 'restore_test')" ;;
  esac
}

psql_run() { # db, sql
  psql -X -q -v ON_ERROR_STOP=1 -d "$1" -c "$2"
}
psql_val() { # db, sql
  psql -X -q -t -A -v ON_ERROR_STOP=1 -d "$1" -c "$2"
}
psql_admin() {
  psql -X -q -v ON_ERROR_STOP=1 -d postgres -c "$1"
}

drop_db() {
  local db="$1"
  # Dupla checagem: nada fora de *_restore_test* é dropado, nem por engano aqui.
  case "$db" in
    *restore_test*) : ;;
    *) return 0 ;;
  esac
  psql -X -q -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid()" \
    >/dev/null 2>&1 || true
  psql -X -q -d postgres -c "DROP DATABASE IF EXISTS \"$db\"" >/dev/null 2>&1 || true
}

cleanup() {
  if [[ -n "${DST_DB:-}" ]]; then drop_db "$DST_DB"; fi
  if [[ -n "${SRC_DB:-}" ]]; then drop_db "$SRC_DB"; fi
  if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
    case "$TMP_DIR" in
      */lean-restore-test.*) rm -rf -- "$TMP_DIR" ;;
      *) echo "[test-restore] AVISO: não removendo TMP_DIR inesperado: $TMP_DIR" >&2 ;;
    esac
  fi
}

on_exit() {
  local rc
  rc=$?
  cleanup
  if [[ "$RESULT" == "PASS" && $rc -eq 0 ]]; then
    echo "[test-restore] PASS"
  else
    echo "[test-restore] FAIL" >&2
    [[ $rc -ne 0 ]] || rc=1
  fi
  exit "$rc"
}
trap on_exit EXIT

guard_db "$SRC_DB"
guard_db "$DST_DB"

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lean-restore-test.XXXXXX")"
BACKUP_DIR="$TMP_DIR/backups"
mkdir -p "$BACKUP_DIR"

# Limpa restos de uma execução anterior (nomes já validados pelo guard_db).
drop_db "$SRC_DB"
drop_db "$DST_DB"

log "criando bancos temporários: $SRC_DB, $DST_DB"
psql_admin "CREATE DATABASE \"$SRC_DB\""
psql_admin "CREATE DATABASE \"$DST_DB\""

log "semeando a fonte (PK, sequência, índice, 3 linhas)"
psql_run "$SRC_DB" "
CREATE TABLE restore_probe (
  id bigserial PRIMARY KEY,
  payload text NOT NULL,
  amount numeric(10,2) NOT NULL,
  created_at timestamptz NOT NULL
);
CREATE INDEX restore_probe_payload_idx ON restore_probe (payload);
INSERT INTO restore_probe (payload, amount, created_at) VALUES
  ('alpha',   1.00, '2024-01-01T00:00:00Z'),
  ('bravo',   2.50, '2024-01-02T00:00:00Z'),
  ('charlie', -3.75, '2024-01-03T00:00:00Z');
"

log "gerando backup local com scripts/backup.sh"
ENV_FILE=/dev/null \
  POSTGRES_HOST="$POSTGRES_HOST" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  POSTGRES_DB="$SRC_DB" \
  BACKUP_DIR="$BACKUP_DIR" \
  RCLONE_BUCKET="" \
  bash "$SCRIPT_DIR/backup.sh"

shopt -s nullglob
dumps=("$BACKUP_DIR"/*.dump)
shopt -u nullglob
[[ ${#dumps[@]} -eq 1 ]] || fail "esperava exatamente 1 dump em $BACKUP_DIR (achei ${#dumps[@]})"
DUMP_FILE="${dumps[0]}"
[[ -s "${DUMP_FILE}.sha256" ]] || fail "sidecar de checksum ausente: ${DUMP_FILE}.sha256"

log "restaurando $(basename "$DUMP_FILE") em $DST_DB"
ENV_FILE=/dev/null \
  POSTGRES_HOST="$POSTGRES_HOST" \
  POSTGRES_PORT="$POSTGRES_PORT" \
  POSTGRES_USER="$POSTGRES_USER" \
  POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  bash "$SCRIPT_DIR/restore.sh" "$DUMP_FILE" --db "$DST_DB" --yes

# ---- Verificação -----------------------------------------------------------
log "verificando o alvo"
src_count="$(psql_val "$SRC_DB" "SELECT count(*) FROM restore_probe")"
[[ "$src_count" == "3" ]] || fail "fonte deveria ter 3 linhas, tem '$src_count'"

dst_table="$(psql_val "$DST_DB" "SELECT coalesce(to_regclass('public.restore_probe')::text, '')")"
[[ -n "$dst_table" ]] || fail "tabela restore_probe não existe no alvo"

dst_count="$(psql_val "$DST_DB" "SELECT count(*) FROM restore_probe")"
[[ "$dst_count" == "$src_count" ]] || fail "contagem divergente: fonte=$src_count alvo=$dst_count"

ROW_HASH_SQL="SELECT md5(coalesce(string_agg(id::text || '|' || payload || '|' || amount::text || '|' || created_at::text, E'\n' ORDER BY id), '')) FROM restore_probe"
src_hash="$(psql_val "$SRC_DB" "$ROW_HASH_SQL")"
dst_hash="$(psql_val "$DST_DB" "$ROW_HASH_SQL")"
[[ -n "$src_hash" && "$src_hash" == "$dst_hash" ]] || fail "conteúdo divergente: fonte=$src_hash alvo=$dst_hash"

idx="$(psql_val "$DST_DB" "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'restore_probe' AND indexname = 'restore_probe_payload_idx'")"
[[ "$idx" == "1" ]] || fail "índice restore_probe_payload_idx ausente no alvo"

pk="$(psql_val "$DST_DB" "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'restore_probe' AND indexname = 'restore_probe_pkey'")"
[[ "$pk" == "1" ]] || fail "PK restore_probe_pkey ausente no alvo"

seq="$(psql_val "$DST_DB" "SELECT count(*) FROM pg_class WHERE relkind = 'S' AND relname = 'restore_probe_id_seq'")"
[[ "$seq" == "1" ]] || fail "sequência restore_probe_id_seq ausente no alvo"

log "tabela, linhas (count + hash), PK, índice e sequência conferem"
RESULT="PASS"
