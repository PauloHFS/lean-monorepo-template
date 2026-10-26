"""Baseline schema: todas as tabelas num único arquivo.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-04 00:00:00

Este é o **baseline** do template: um único arquivo, sem histórico
incremental. Não existem migrations 0002+ neste repositório. Para evoluir o
schema, crie uma nova revision a partir daqui com
`alembic revision --autogenerate -m "..."`.

Conteúdo (ordem de criação):

  1. Extensões            (citext obrigatória; pg_cron opcional)
  2. users                (com trigger updated_at)
  3. sessions             (FK -> users)
  4. kv_cache             (UNLOGGED)
  5. rate_limits          (rate-limit por chave)
  6. jobs                 (job_rate_limits + dead_letters)
  7. 2FA em users         (TOTP cols + recovery_codes + passkeys)
  8. pg_cron jobs         (limpezas agendadas, só se pg_cron existir)
  9. Procrastinate schema

Portabilidade: UUIDs usam `gen_random_uuid()` (built-in desde o PG13), então
uuid-ossp não é necessária. `pg_cron` é opcional — em bancos gerenciados
(RDS/Aurora/Cloud SQL) sem a extensão o schema sobe e os jobs de limpeza são
omitidos com aviso, em vez de o `alembic upgrade head` falhar.

Idempotente: usa IF NOT EXISTS nos CREATE TABLE principais.
"""
from typing import Sequence, Union

from sqlalchemy import text

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =============================================================================
# pg_cron: jobs globais (schema `cron`).
# =============================================================================
_CRON_JOBS = [
    {
        "name": "cleanup-kv-cache",
        "schedule": "0 * * * *",  # hourly
        "sql": """
            DELETE FROM kv_cache
             WHERE expires_at IS NOT NULL
               AND expires_at < now() - interval '1 day'
        """,
    },
    {
        "name": "cleanup-rate-limits",
        "schedule": "*/15 * * * *",  # every 15min
        "sql": """
            DELETE FROM rate_limits
             WHERE window_start < now() - interval '1 day'
        """,
    },
    {
        "name": "cleanup-job-rate-limits",
        "schedule": "*/15 * * * *",  # every 15min
        "sql": """
            DELETE FROM job_rate_limits
             WHERE window_start < now() - interval '1 day'
        """,
    },
    {
        "name": "cleanup-dead-letters",
        "schedule": "30 3 * * *",  # daily 03:30
        "sql": """
            DELETE FROM dead_letters
             WHERE status != 'pending'
               AND created_at < now() - interval '90 days'
        """,
    },
    {
        "name": "cleanup-recovery-codes-used",
        "schedule": "0 3 * * *",  # daily 03:00
        "sql": """
            DELETE FROM totp_recovery_codes
             WHERE used_at IS NOT NULL
               AND used_at < now() - interval '90 days'
        """,
    },
    {
        "name": "cleanup-old-sessions",
        "schedule": "0 4 * * *",  # daily 04:00
        "sql": """
            DELETE FROM sessions
             WHERE expires_at < now() - interval '7 days'
        """,
    },
]


def _extension_installed(name: str) -> bool:
    """True se a extensão já está instalada no banco alvo."""
    return bool(
        op.get_bind()
        .execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = :name)"),
            {"name": name},
        )
        .scalar()
    )


def _apply_procrastinate_schema() -> None:
    """Aplica procrastinate/sql/schema.sql via connector sync (psycopg3).

    Imports locais: evitam custo/side-effects ao carregar o grafo de revisões.
    """
    from app.core.config import settings
    from procrastinate import SyncPsycopgConnector
    from procrastinate.schema import SchemaManager

    connector = SyncPsycopgConnector(conninfo=settings.database_url_procrastinate)
    connector.open()
    try:
        SchemaManager(connector=connector).apply_schema()
    finally:
        connector.close()


# =============================================================================
# UP
# =============================================================================
def upgrade() -> None:
    # ---------- 1. Extensões -------------------------------------------------
    # citext é usada pela coluna users.email: sem ela o schema é impossível,
    # então a criação é obrigatória (não opcional).
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")
    # UUIDs usam gen_random_uuid() (built-in desde o PG13): uuid-ossp não entra.
    # pg_cron é opcional e só é criada se o servidor a oferecer (RDS/Cloud SQL
    # podem não a ter, ou tê-la sem shared_preload_libraries). A falha de
    # criação é rebaixada a aviso; o scheduling abaixo já checa a instalação.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron'
            ) THEN
                BEGIN
                    CREATE EXTENSION IF NOT EXISTS pg_cron;
                EXCEPTION WHEN OTHERS THEN
                    RAISE NOTICE 'pg_cron disponível mas não criada (%): jobs de limpeza omitidos', SQLERRM;
                END;
            END IF;
        END $$;
    """)

    # ---------- 2. users -----------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email         CITEXT NOT NULL UNIQUE,
            password_hash TEXT   NOT NULL,
            full_name     TEXT,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            is_superuser  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=False,
        if_not_exists=True,
    )

    # ---------- updated_at trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    # Um statement por op.execute: o Alembic roda com engine async (asyncpg),
    # que usa prepared statement e rejeita múltiplos comandos no mesmo
    # ("cannot insert multiple commands into a prepared statement").
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users;")
    op.execute("""
        CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ---------- 3. sessions (server-side) ------------------------------------
    # Token opaco, armazenamos só o hash; cookie envia o token cru.
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash  TEXT NOT NULL UNIQUE,
            user_agent  TEXT,
            ip          INET,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ NOT NULL
        );
    """)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], if_not_exists=True)
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], if_not_exists=True)

    # ---------- 4. kv_cache (UNLOGGED) ---------------------------------------
    # UNLOGGED: super rápido, mas não replicado/recuperável — exatamente o que
    # queremos para cache volátil. Se precisar persistir, mude para LOGGED.
    op.execute("""
        CREATE UNLOGGED TABLE IF NOT EXISTS kv_cache (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            expires_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.create_index("ix_kv_cache_expires_at", "kv_cache", ["expires_at"], if_not_exists=True)

    # ---------- 5. rate_limits -----------------------------------------------
    # chave opaca (recomendação: "ip:endpoint" ou "user:endpoint"), janela fixa.
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key          TEXT PRIMARY KEY,
            count        INTEGER NOT NULL DEFAULT 0,
            window_start TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rate_limits_window_start ON rate_limits (window_start);")

    # ---------- 6. jobs: rate limit por kind/chave + dead-letter queue ------
    op.execute("""
        CREATE TABLE IF NOT EXISTS job_rate_limits (
            kind         TEXT NOT NULL,
            key          TEXT NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            count        INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (kind, key, window_start)
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS dead_letters (
            id              SERIAL PRIMARY KEY,
            kind            TEXT NOT NULL,
            key             TEXT NOT NULL DEFAULT '',
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
            error           TEXT NOT NULL,
            retries         INTEGER NOT NULL DEFAULT 0,
            original_job_id INTEGER,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at     TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dead_letters_status_created
        ON dead_letters (status, created_at);
    """)

    # ---------- 7. 2FA: TOTP + recovery codes + WebAuthn passkeys ------------
    op.execute("""
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS totp_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS totp_secret_enc  BYTEA,
          ADD COLUMN IF NOT EXISTS totp_confirmed_at TIMESTAMPTZ;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS totp_recovery_codes (
            id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            used_at   TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_recovery_codes_user ON totp_recovery_codes (user_id);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_passkeys (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            credential_id BYTEA NOT NULL,
            public_key    BYTEA NOT NULL,
            sign_count    BIGINT NOT NULL DEFAULT 0,
            name          TEXT NOT NULL DEFAULT 'passkey',
            transports    TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at  TIMESTAMPTZ
        );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_passkeys_credential_id ON user_passkeys (credential_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_passkeys_user ON user_passkeys (user_id);")

    # ---------- 8. pg_cron jobs ---------------------------------------------
    # Só agenda se a extensão estiver realmente instalada. Sem pg_cron o
    # schema continua válido; a limpeza periódica fica a cargo do operador.
    if _extension_installed("pg_cron"):
        bind = op.get_bind()
        for job in _CRON_JOBS:
            bind.execute(
                text("SELECT cron.schedule(:name, :schedule, :command)"),
                {
                    "name": job["name"],
                    "schedule": job["schedule"],
                    "command": job["sql"].strip(),
                },
            )
    else:
        print("[migration] pg_cron ausente: jobs de limpeza não agendados")

    # ---------- 9. Procrastinate schema -------------------------------------
    # Schema oficial vem direto da lib (nunca duplicar ~600 linhas de SQL).
    _apply_procrastinate_schema()


# =============================================================================
# DOWN
# =============================================================================
def downgrade() -> None:
    # As tabelas procrastinate_* são geridas pela lib; não as dropamos aqui.
    # Um downgrade que precise removê-las deve fazê-lo à parte.

    bind = op.get_bind()
    if _extension_installed("pg_cron"):
        for job in _CRON_JOBS:
            bind.execute(text("SELECT cron.unschedule(:name)"), {"name": job["name"]})

    op.execute("DROP TABLE IF EXISTS user_passkeys;")
    op.execute("DROP TABLE IF EXISTS totp_recovery_codes;")
    op.execute("""
        ALTER TABLE users
          DROP COLUMN IF EXISTS totp_enabled,
          DROP COLUMN IF EXISTS totp_secret_enc,
          DROP COLUMN IF EXISTS totp_confirmed_at;
    """)

    op.execute("DROP TABLE IF EXISTS rate_limits;")
    op.execute("DROP TABLE IF EXISTS kv_cache;")
    op.execute("DROP TABLE IF EXISTS dead_letters;")
    op.execute("DROP TABLE IF EXISTS job_rate_limits;")

    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")

    op.execute("DROP TABLE IF EXISTS sessions;")
    op.execute("DROP TABLE IF EXISTS users;")