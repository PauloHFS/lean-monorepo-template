"""kv_cache: cache key/value em Postgres (UNLOGGED).

Revision ID: 0003_kv_cache
Revises: 0002_rate_limits
Create Date: 2026-10-02 00:00:00

UNLOGGED: super rápido, não replicado, volátil. Ideal para cache efêmero.
Se precisar de durabilidade, troque para LOGGED e migre os dados.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0003_kv_cache"
down_revision: Union[str, None] = "0002_rate_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE UNLOGGED TABLE IF NOT EXISTS kv_cache (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            expires_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_kv_cache_expires_at ON kv_cache (expires_at);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kv_cache_expires_at;")
    op.execute("DROP TABLE IF EXISTS kv_cache;")