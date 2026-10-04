"""rate_limits: rate-limit por chave (ex.: IP + path), janela fixa.

Revision ID: 0002_rate_limits
Revises: 0001_initial_schema
Create Date: 2026-10-02 00:00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002_rate_limits"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            -- chave opaca (recomendação: "ip:endpoint" ou "user:endpoint")
            key          TEXT PRIMARY KEY,
            -- contador dentro da janela atual
            count        INTEGER NOT NULL DEFAULT 0,
            -- início da janela (UTC)
            window_start TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    # Para o coletor de lixo de janelas expiradas
    op.execute("CREATE INDEX IF NOT EXISTS ix_rate_limits_window_start ON rate_limits (window_start);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rate_limits_window_start;")
    op.execute("DROP TABLE IF EXISTS rate_limits;")