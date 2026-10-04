"""Limpeza automática de tabelas efêmeras via pg_cron.

Revision ID: 0005_pg_cron_cleanup
Revises: 0004_2fa
Create Date: 2026-10-04 00:00:00

pg_cron já é habilitado em postgres-init/01-extensions.sql. Aqui agendamos
os jobs. O schedule roda no fuso UTC; pg_cron usa now() do servidor.
"""
from typing import Sequence, Union

from sqlalchemy import text

from alembic import op


revision: str = "0005_pg_cron_cleanup"
down_revision: Union[str, None] = "0004_2fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# pg_cron jobs são globais (schema `cron`). Limpa tudo no downgrade.
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


def upgrade() -> None:
    for job in _CRON_JOBS:
        # cron.schedule(jobname, schedule, command) é a função padrão pg_cron.
        # Usamos text() para escapar o SQL com segurança.
        op.execute(
            text(
                "SELECT cron.schedule(:name, :schedule, :command)"
            ),
            {
                "name": job["name"],
                "schedule": job["schedule"],
                "command": job["sql"].strip(),
            },
        )


def downgrade() -> None:
    for job in _CRON_JOBS:
        op.execute(text("SELECT cron.unschedule(:name)"), {"name": job["name"]})