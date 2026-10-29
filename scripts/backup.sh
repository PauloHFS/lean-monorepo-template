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
#                               (e o sidecar .sha256) em BACKUP_DIR, com
#                               retenção de BACKUP_KEEP_COUNT arquivos.
#
# Confidencialidade: o dump contém hashes de senha, TOTP cifrado e PII. Ele é
# criado com umask 077 (0600) e removido se o backup falhar. Defina
# BACKUP_ENCRYPT_PASSPHRASE para gravá-lo/enviá-lo cifrado (AES-256-CBC +
# PBKDF2). Sem a passphrase, o dump sai em texto claro e o script avisa.
#
# Modo container (POSTGRES_CONTAINER preenchido):
#   No deploy do Coolify a porta do Postgres não é publicada no host, então o
#   pg_dump roda dentro do container do Postgres (docker compose exec). No host
#   continuam a cifragem (openssl), o envio (rclone), o checksum e a retenção.
#
# Variáveis:
#   POSTGRES_DB, POSTGRES_USER (obrigatórias)
#   POSTGRES_HOST (obrigatória só no modo host), POSTGRES_PASSWORD, POSTGRES_PORT (5432)
#   POSTGRES_CONTAINER (vazio = modo host; com valor = modo container)
#   BACKUP_COMPOSE_FILE (default: <repo>/docker-compose.yml; usado no modo container)
#   RCLONE_BUCKET (vazio = modo local), RCLONE_REMOTE_NAME (r2)
#   BACKUP_ENCRYPT_PASSPHRASE (vazio = sem cifra; use uma passphrase forte)
#   BACKUP_KEEP_DAYS (14, retenção remota)
#   BACKUP_KEEP_COUNT (14, retenção local: quantos dumps manter)
#   BACKUP_DIR (/tmp/lean-monorepo-backups)
#
# Sanidade: o dump só é considerado válido se `pg_restore --list` conseguir
# lê-lo. Em caso de falha, o arquivo parcial é removido e nada é enviado.
# =============================================================================
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Uso: scripts/backup.sh [--help]

Gera um dump do Postgres em BACKUP_DIR e, se RCLONE_BUCKET estiver preenchido,
envia para r2:<bucket>/db/ e remove o dump local.

Com RCLONE_BUCKET vazio (modo local), nada é enviado e o dump permanece em
BACKUP_DIR junto do sidecar <arquivo>.sha256. A retenção local mantém os
últimos BACKUP_KEEP_COUNT dumps.

Com BACKUP_ENCRYPT_PASSPHRASE definida, o dump é cifrado com
`openssl enc -aes-256-cbc -pbkdf2 -salt` (extensão .dump.enc) antes de ser
mantido/enviado. Sem ela, o dump é gravado em texto claro e um aviso é
impresso.

Variáveis:
  POSTGRES_DB, POSTGRES_USER                     obrigatórias
  POSTGRES_HOST                                  obrigatória no modo host
  POSTGRES_PASSWORD, POSTGRES_PORT               opcionais (5432)
  POSTGRES_CONTAINER                             vazio = modo host (pg_dump local)
  BACKUP_COMPOSE_FILE                                   default: <repo>/docker-compose.yml
  RCLONE_BUCKET                                  vazio = modo local
  RCLONE_REMOTE_NAME                             default: r2
  BACKUP_ENCRYPT_PASSPHRASE                      vazio = dump não cifrado
  BACKUP_KEEP_DAYS                               default: 14 (retenção remota)
  BACKUP_KEEP_COUNT                              default: 14 (retenção local)
  BACKUP_DIR                                     default: /tmp/lean-monorepo-backups
  ENV_FILE                                       default: .env

Modo container (POSTGRES_CONTAINER preenchido):
  O dump é gerado dentro do container do Postgres via
  `docker compose -f BACKUP_COMPOSE_FILE exec -T <serviço> pg_dump`, porque no deploy
  do Coolify a porta do Postgres não é publicada no host. A sanidade do dump
  também roda dentro do container (o host pode não ter pg_restore). Cifragem,
  checksum, envio (rclone) e retenção continuam no host.

Exemplos:
  ./scripts/backup.sh
  BACKUP_ENCRYPT_PASSPHRASE='...' ./scripts/backup.sh
  RCLONE_BUCKET= ./scripts/backup.sh
  POSTGRES_CONTAINER=postgres ./scripts/backup.sh
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
# O .env tem precedência (semântica já existente no script), mas um valor VAZIO
# no .env não pode apagar o que veio do shell (POSTGRES_CONTAINER=postgres
# ./scripts/backup.sh precisa vencer o `POSTGRES_CONTAINER=` do .env).
_shell_container="${POSTGRES_CONTAINER:-}"
_shell_compose_file="${BACKUP_COMPOSE_FILE:-}"
_shell_backup_dir="${BACKUP_DIR:-}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
fi
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-$_shell_container}"
BACKUP_COMPOSE_FILE="${BACKUP_COMPOSE_FILE:-$_shell_compose_file}"
if [[ -n "$_shell_backup_dir" ]]; then
  BACKUP_DIR="$_shell_backup_dir"
fi

# POSTGRES_CONTAINER vazio = modo host (pg_dump local, como sempre).
# Se POSTGRES_CONTAINER estiver preenchido, mas não houver `docker` no PATH e
# já estivermos rodando dentro de um container (/.dockerenv) com `pg_dump`
# local, muda automaticamente para o modo local (ex.: Scheduled Task do Coolify
# rodando dentro do container `postgres`).
if [[ -n "$POSTGRES_CONTAINER" ]] && ! command -v docker >/dev/null 2>&1 && [[ -f /.dockerenv ]] && command -v pg_dump >/dev/null 2>&1; then
  POSTGRES_CONTAINER=""
  POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
fi

# Com valor = modo container: o dump sai de dentro do container do Postgres
# (docker compose exec), então POSTGRES_HOST/PORT não são usados.
if [[ -z "$POSTGRES_CONTAINER" ]]; then
  : "${POSTGRES_HOST:?POSTGRES_HOST não definido}"
fi
: "${POSTGRES_DB:?POSTGRES_DB não definido}"
: "${POSTGRES_USER:?POSTGRES_USER não definido}"
if [[ -z "${BACKUP_COMPOSE_FILE:-}" ]]; then
  _repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [[ -f "${_repo_root}/docker-compose.yml" ]]; then
    BACKUP_COMPOSE_FILE="${_repo_root}/docker-compose.yml"
  elif [[ -f "${_repo_root}/docker-compose.yaml" ]]; then
    BACKUP_COMPOSE_FILE="${_repo_root}/docker-compose.yaml"
  else
    BACKUP_COMPOSE_FILE="${_repo_root}/docker-compose.yml"
  fi
fi
if [[ -n "$POSTGRES_CONTAINER" ]]; then
  if [[ -z "${COMPOSE_PROJECT_NAME:-}" && -n "${COOLIFY_RESOURCE_UUID:-}" ]]; then
    export COMPOSE_PROJECT_NAME="$COOLIFY_RESOURCE_UUID"
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "[backup] ERRO: POSTGRES_CONTAINER=$POSTGRES_CONTAINER, mas docker não está no PATH" >&2
    exit 1
  fi
  if [[ ! -f "$BACKUP_COMPOSE_FILE" ]]; then
    echo "[backup] ERRO: BACKUP_COMPOSE_FILE não encontrado: $BACKUP_COMPOSE_FILE" >&2
    exit 1
  fi
fi

: "${RCLONE_REMOTE_NAME:=r2}"
RCLONE_BUCKET="${RCLONE_BUCKET:-}"
BACKUP_ENCRYPT_PASSPHRASE="${BACKUP_ENCRYPT_PASSPHRASE:-}"
: "${BACKUP_KEEP_DAYS:=14}"
: "${BACKUP_KEEP_COUNT:=14}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/lean-monorepo-backups}"
# Se estiver rodando dentro do container postgres (com volume em /var/lib/postgresql)
# e BACKUP_DIR ainda estiver no default efêmero /tmp/lean-monorepo-backups, grava em
# /var/lib/postgresql/backups para persistir no volume pgdata entre deploys.
if [[ -f /.dockerenv && -d /var/lib/postgresql && "$BACKUP_DIR" == "/tmp/lean-monorepo-backups" && -z "$_shell_backup_dir" ]]; then
  BACKUP_DIR="/var/lib/postgresql/backups"
fi

# Se RCLONE_BUCKET estiver preenchido e RCLONE_CONFIG_R2_* ainda não estiverem
# definidas, mapeia automaticamente R2_ACCOUNT_ID / R2_ACCESS_KEY_ID /
# R2_SECRET_ACCESS_KEY (ou R2_ENDPOINT) para variáveis nativas do rclone.
# Isso permite configurar o Cloudflare R2 apenas com variáveis no .env do Coolify,
# sem precisar criar ~/.config/rclone/rclone.conf na VPS.
if [[ -n "$RCLONE_BUCKET" && "${RCLONE_REMOTE_NAME}" == "r2" ]]; then
  export RCLONE_CONFIG_R2_TYPE="${RCLONE_CONFIG_R2_TYPE:-s3}"
  export RCLONE_CONFIG_R2_PROVIDER="${RCLONE_CONFIG_R2_PROVIDER:-Cloudflare}"
  export RCLONE_CONFIG_R2_NO_CHECK_BUCKET="${RCLONE_CONFIG_R2_NO_CHECK_BUCKET:-true}"
  if [[ -n "${R2_ACCESS_KEY_ID:-}" && -z "${RCLONE_CONFIG_R2_ACCESS_KEY_ID:-}" ]]; then
    export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
  fi
  if [[ -n "${R2_SECRET_ACCESS_KEY:-}" && -z "${RCLONE_CONFIG_R2_SECRET_ACCESS_KEY:-}" ]]; then
    export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
  fi
  if [[ -z "${RCLONE_CONFIG_R2_ENDPOINT:-}" ]]; then
    if [[ -n "${R2_ENDPOINT:-}" ]]; then
      export RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
    elif [[ -n "${R2_ACCOUNT_ID:-}" ]]; then
      export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    fi
  fi
fi

# Auto-instala openssl / rclone no Alpine (ex.: container postgres:18-alpine em
# Scheduled Task do Coolify) caso sejam necessários e não estejam presentes.
if [[ -n "$BACKUP_ENCRYPT_PASSPHRASE" ]] && ! command -v openssl >/dev/null 2>&1 && command -v apk >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
  echo "[backup] instalando openssl via apk..."
  apk add --no-cache -q openssl
fi
if [[ -n "$RCLONE_BUCKET" ]] && ! command -v rclone >/dev/null 2>&1 && command -v apk >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
  echo "[backup] instalando rclone via apk..."
  apk add --no-cache -q rclone
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
KEEP_DAYS="${BACKUP_KEEP_DAYS}"
PLAIN_FILE="${BACKUP_DIR}/.${POSTGRES_DB}_${TS}.plain.dump"
if [[ -n "$BACKUP_ENCRYPT_PASSPHRASE" ]]; then
  OUT_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TS}.dump.enc"
else
  OUT_FILE="${BACKUP_DIR}/${POSTGRES_DB}_${TS}.dump"
fi
SHA_FILE="${OUT_FILE}.sha256"

# Remove o plaintext e artefatos parciais em qualquer saída que não seja de
# sucesso. O dump final só sobrevive se o script chegar ao fim (modo local) ou
# se já tiver sido enviado (modo remoto).
cleanup() {
  local rc=$?
  rm -f -- "$PLAIN_FILE"
  if [[ $rc -ne 0 ]]; then
    rm -f -- "$OUT_FILE" "$SHA_FILE"
  fi
  exit "$rc"
}
trap cleanup EXIT

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

if [[ -n "$BACKUP_ENCRYPT_PASSPHRASE" ]]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "[backup] ERRO: BACKUP_ENCRYPT_PASSPHRASE definida, mas openssl não está no PATH" >&2
    exit 1
  fi
  echo "[backup] cifrando com openssl (aes-256-cbc/pbkdf2) -> $(basename "$OUT_FILE")"
else
  echo "[backup] AVISO: BACKUP_ENCRYPT_PASSPHRASE vazia — o dump será gravado/enviado SEM CRIPTOGRAFIA (hashes de senha, TOTP e PII em texto claro)." >&2
fi

echo "[backup] gerando $PLAIN_FILE (formato custom, comprimido)"
if [[ -n "$POSTGRES_CONTAINER" ]]; then
  # Dentro do container o socket local é trust: sem PGPASSWORD e sem host/porta.
  docker compose -f "$BACKUP_COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
    pg_dump \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -Fc \
    -Z 9 \
    --no-owner \
    --no-privileges >"$PLAIN_FILE"
else
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
    -h "$POSTGRES_HOST" \
    -p "${POSTGRES_PORT:-5432}" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -Fc \
    -Z 9 \
    --no-owner \
    --no-privileges >"$PLAIN_FILE"
fi
chmod 600 "$PLAIN_FILE"

# Sanidade: arquivo não vazio E legível pelo pg_restore (formato custom válido).
if [[ ! -s "$PLAIN_FILE" ]]; then
  echo "[backup] ERRO: dump vazio: $PLAIN_FILE" >&2
  exit 1
fi
if [[ -n "$POSTGRES_CONTAINER" ]]; then
  # O host pode não ter pg_restore: a listagem roda no container, dump via stdin.
  if ! docker compose -f "$BACKUP_COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" pg_restore --list <"$PLAIN_FILE" >/dev/null; then
    echo "[backup] ERRO: dump ilegível (pg_restore --list falhou): $PLAIN_FILE" >&2
    exit 1
  fi
else
  if ! pg_restore --list "$PLAIN_FILE" >/dev/null; then
    echo "[backup] ERRO: dump ilegível (pg_restore --list falhou): $PLAIN_FILE" >&2
    exit 1
  fi
fi

if [[ -n "$BACKUP_ENCRYPT_PASSPHRASE" ]]; then
  # -pass stdin evita expor a passphrase em argv (visível em ps).
  if ! printf '%s' "$BACKUP_ENCRYPT_PASSPHRASE" |
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "$PLAIN_FILE" -out "$OUT_FILE" -pass stdin; then
    echo "[backup] ERRO: falha ao cifrar o dump" >&2
    exit 1
  fi
  rm -f -- "$PLAIN_FILE"
else
  mv -- "$PLAIN_FILE" "$OUT_FILE"
fi
chmod 600 "$OUT_FILE"

# Checksum: sha256sum no Linux, shasum -a 256 no macOS.
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$OUT_FILE" >"$SHA_FILE"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$OUT_FILE" >"$SHA_FILE"
else
  echo "[backup] ERRO: sha256sum/shasum não encontrado" >&2
  exit 1
fi
chmod 600 "$SHA_FILE"
echo "[backup] sha256: $(<"$SHA_FILE")"

# Retenção local: mantém os BACKUP_KEEP_COUNT mais recentes (nome ordena por TS).
prune_local() {
  local keep="$1"
  find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name "${POSTGRES_DB}_*.dump" -o -name "${POSTGRES_DB}_*.dump.enc" \) -print |
    sort -r |
    tail -n +"$((keep + 1))" |
    while IFS= read -r old; do
      rm -f -- "$old" "${old}.sha256"
    done
}

if [[ -n "$RCLONE_BUCKET" ]]; then
  REMOTE_PATH="${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}/db/$(basename "$OUT_FILE")"
  echo "[backup] enviando para $REMOTE_PATH"
  rclone copyto "$OUT_FILE" "$REMOTE_PATH" --progress --s3-no-check-bucket

  # Limpeza local só depois do upload bem-sucedido.
  rm -f -- "$OUT_FILE" "$SHA_FILE"

  # Limpeza remota: apaga dumps com mais de KEEP_DAYS dias. Falha não é fatal,
  # mas precisa aparecer no log (antes falhava em silêncio).
  echo "[backup] aplicando retenção (${KEEP_DAYS} dias) em ${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}"
  if ! rclone delete "${RCLONE_REMOTE_NAME}:${RCLONE_BUCKET}/db" \
    --min-age "${KEEP_DAYS}d" \
    --include "${POSTGRES_DB}_*"; then
    echo "[backup] AVISO: falha na retenção remota; dumps antigos podem sobrar" >&2
  fi
else
  echo "[backup] RCLONE_BUCKET vazio: modo local, nada enviado."
  echo "[backup] dump mantido em $OUT_FILE (+ $(basename "$SHA_FILE"))"
  prune_local "$BACKUP_KEEP_COUNT"
  echo "[backup] retenção local: mantendo os últimos ${BACKUP_KEEP_COUNT} dumps em $BACKUP_DIR"
fi

echo "[backup] ok."
