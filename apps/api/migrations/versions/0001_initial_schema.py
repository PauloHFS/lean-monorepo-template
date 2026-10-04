"""initial schema: tudo num único arquivo.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-04 00:00:00

Este é um *template*, não um app em produção: não há razão para manter
o histórico incremental de migrations. Se você for usar este template em
um prod, faça a partitura a partir deste commit:

    for rev in 0001_initial_schema 0002_rate_limits 0003_kv_cache 0004_2fa \\
               0005_pg_cron_cleanup 0006_procrastinate_jobs; do
        git show $rev:migrations/versions/$rev.py > old_migrations/$rev.py
    done

Depois crie novas migrations com `alembic revision --autogenerate -m "..."`.

Conteúdo (ordem de criação):

  1. Extensões            (citext)
  2. users                (com trigger updated_at)
  3. sessions             (FK -> users)
  4. background_jobs      (legado; mantido para rollback)
  5. kv_cache             (UNLOGGED)
  6. rate_limits          (rate-limit por chave)
  7. 2FA em users         (TOTP cols + recovery_codes + passkeys)
  8. pg_cron jobs         (limpezas agendadas)
  9. Procrastinate schema + dead_letters + job_rate_limits

Idempotente: usa IF NOT EXISTS nos CREATE TABLE principais.
"""
from typing import Sequence, Union

from sqlalchemy import text
from sqlalchemy.dialects import postgresql

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
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")
    # uuid-ossp é criada em scripts/postgres-init; aqui só garantimos.
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    # ---------- 2. users -----------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

    # ---------- updated_at trigger (criado cedo p/ atender users/background_jobs)
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ---------- 3. sessions (server-side) ------------------------------------
    # Token opaco, armazenamos só o hash; cookie envia o token cru.
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

    # ---------- 4. background_jobs (fila Postgres-first) ---------------------
    # Legado: mantido para rollback/auditoria. O runner ativo é Procrastinate.
    op.execute("""
        CREATE TABLE IF NOT EXISTS background_jobs (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            queue         TEXT NOT NULL DEFAULT 'default',
            kind          TEXT NOT NULL,
            payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
            status        TEXT NOT NULL DEFAULT 'pending',
            attempts      INTEGER NOT NULL DEFAULT 0,
            max_attempts  INTEGER NOT NULL DEFAULT 5,
            run_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            locked_at     TIMESTAMPTZ,
            locked_by     TEXT,
            started_at    TIMESTAMPTZ,
            finished_at   TIMESTAMPTZ,
            last_error    TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_jobs_ready
        ON background_jobs (queue, status, run_at)
        WHERE status IN ('pending', 'failed')
              AND attempts < max_attempts;
    """)
    op.create_index("ix_jobs_kind", "background_jobs", ["kind"], if_not_exists=True)

    for tbl in ("users", "background_jobs"):
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};
            CREATE TRIGGER trg_{tbl}_updated_at
            BEFORE UPDATE ON {tbl}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)

    # ---------- 5. kv_cache (UNLOGGED) ---------------------------------------
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

    # ---------- 6. rate_limits -----------------------------------------------
    # chave opaca (recomendação: "ip:endpoint" ou "user:endpoint"), janela fixa.
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key          TEXT PRIMARY KEY,
            count        INTEGER NOT NULL DEFAULT 0,
            window_start TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_rate_limits_window_start ON rate_limits (window_start);")

    # ---------- 7. 2FA: TOTP + recovery codes + WebAuthn passkeys ------------
    op.execute("""
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS totp_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS totp_secret_enc  BYTEA,
          ADD COLUMN IF NOT EXISTS totp_confirmed_at TIMESTAMPTZ;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS totp_recovery_codes (
            id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            used_at   TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_recovery_codes_user ON totp_recovery_codes (user_id);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_passkeys (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

    # ---------- 9. Procrastinate + DLQ + rate-limit por kind ----------------
    # Schema oficial vem direto da lib (nunca duplicar ~600 linhas de SQL).
    _apply_procrastinate_schema()

    op.create_table(
        "dead_letters",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("job_id", sa.BigInteger, nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("queue", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_dead_letters_failed_at", "dead_letters", ["failed_at"])
    op.create_index("ix_dead_letters_kind", "dead_letters", ["kind"])

    op.create_table(
        "job_rate_limits",
        sa.Column("kind", sa.String(64), primary_key=True),
        sa.Column("max_per_minute", sa.Integer, nullable=False),
        sa.Column("burst", sa.Integer, server_default="5", nullable=False),
    )


# =============================================================================
# DOWN
# =============================================================================
def downgrade() -> None:
    op.drop_table("job_rate_limits")
    op.drop_table("dead_letters")
    # As tabelas procrastinate_* são geridas pela lib; não as dropamos aqui.
    # Um downgrade que precise removê-las deve fazê-lo à parte.

    bind = op.get_bind()
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

    for tbl in ("background_jobs", "users"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")

    op.execute("DROP TABLE IF EXISTS background_jobs;")
    op.execute("DROP TABLE IF EXISTS sessions;")
    op.execute("DROP TABLE IF EXISTS users;")