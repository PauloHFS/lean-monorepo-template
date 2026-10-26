"""Drop dead lower(email) index and add users.created_at index.

Revision ID: 0002_drop_dead_add_created_at
Revises: 0001_initial_schema
Create Date: 2026-10-26 00:00:00

`ix_users_email_lower` (lower(email), não-único) nunca foi usado: o login
compara `email = :e` direto na coluna CITEXT e usa o índice único implícito
de `users.email` (citext_ops). Nenhuma query chama `lower(email)`.

`GET /users` pagina com `ORDER BY created_at DESC LIMIT/OFFSET`; sem índice
em `created_at` o Postgres ordena a tabela inteira. O índice simples atende:
o btree em `created_at` entrega as linhas já na ordem DESC e com LIMIT/OFFSET.
Um índice composto é desnecessário porque a query não filtra por outras
colunas e o `SELECT` só projeta colunas já presentes na linha da tabela.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002_drop_dead_add_created_at"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_users_email_lower", table_name="users", if_exists=True)
    op.create_index("ix_users_created_at", "users", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_users_created_at", table_name="users")
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=False,
        if_not_exists=True,
    )
