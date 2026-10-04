"""initial schema: users, sessions, background_jobs, kv_cache

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-01 00:00:00

Cria o esqueleto relacional mínimo + filas + cache + sessão server-side.
Idempotente: usa IF NOT EXISTS nos CREATE TABLE principais.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# =============================================================================
# UP
# =============================================================================
def upgrade() -> None:
    # ---------- users --------------------------------------------------------
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
    # citext requer a extensão (criada em scripts/postgres-init)
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")

    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=False,
        if_not_exists=True,
    )

    # ---------- sessions (server-side) --------------------------------------
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

    # ---------- background_jobs (fila Postgres-first) ----------------------
    # Colunas suficientes para SKIP LOCKED + visibilidade + retries.
    op.execute("""
        CREATE TABLE IF NOT EXISTS background_jobs (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            queue         TEXT NOT NULL DEFAULT 'default',
            kind          TEXT NOT NULL,                -- ex.: "email.send"
            payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
            status        TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed|cancelled
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
    # O índice composto é o que faz o SKIP LOCKED escalar.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_jobs_ready
        ON background_jobs (queue, status, run_at)
        WHERE status IN ('pending', 'failed')
              AND attempts < max_attempts;
    """)
    op.create_index("ix_jobs_kind", "background_jobs", ["kind"], if_not_exists=True)

    # ---------- kv_cache (UNLOGGED) -----------------------------------------
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

    # ---------- updated_at trigger -------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    for tbl in ("users", "background_jobs"):
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};
            CREATE TRIGGER trg_{tbl}_updated_at
            BEFORE UPDATE ON {tbl}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


# =============================================================================
# DOWN
# =============================================================================
def downgrade() -> None:
    for tbl in ("background_jobs", "users"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
    op.execute("DROP TABLE IF EXISTS kv_cache;")
    op.execute("DROP TABLE IF EXISTS background_jobs;")
    op.execute("DROP TABLE IF EXISTS sessions;")
    op.execute("DROP TABLE IF EXISTS users;")
