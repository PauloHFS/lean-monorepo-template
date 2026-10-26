"""Portabilidade do baseline: extensões opcionais não podem ser obrigatórias.

AD-008: o teste lê a migration como texto — nada aqui abre conexão com
Postgres. O objetivo é impedir que alguém reintroduza um `CREATE EXTENSION`
incondicional (uuid-ossp/pg_cron) ou chame `cron.schedule` sem checar se o
pg_cron existe, quebrando `alembic upgrade head` em bancos gerenciados.
"""

from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0001_initial_schema.py"
)
SOURCE = MIGRATION_PATH.read_text(encoding="utf-8")


def _index(text: str, needle: str, *, start: int = 0) -> int:
    position = text.find(needle, start)
    assert position != -1, f"trecho ausente na migration: {needle!r}"
    return position


def test_uuid_ossp_is_not_required() -> None:
    assert "uuid_generate_v4" not in SOURCE
    assert 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"' not in SOURCE
    assert "CREATE EXTENSION IF NOT EXISTS uuid-ossp" not in SOURCE
    assert SOURCE.count("DEFAULT gen_random_uuid()") == 4


def test_required_citext_is_still_created() -> None:
    # users.email é CITEXT: sem citext o schema é impossível.
    assert "CREATE EXTENSION IF NOT EXISTS citext;" in SOURCE


def test_pg_cron_creation_is_guarded_by_availability() -> None:
    create_at = _index(SOURCE, "CREATE EXTENSION IF NOT EXISTS pg_cron")
    guard_at = _index(SOURCE, "FROM pg_available_extensions WHERE name = 'pg_cron'")
    assert guard_at < create_at, "CREATE EXTENSION pg_cron fora do guard de disponibilidade"


def test_cron_schedule_is_guarded_by_installed_extension() -> None:
    schedule_at = _index(SOURCE, "cron.schedule(")
    guard_at = _index(SOURCE, 'if _extension_installed("pg_cron"):')
    assert guard_at < schedule_at, "cron.schedule chamado sem checar a instalação do pg_cron"


def test_downgrade_unschedules_only_when_pg_cron_is_installed() -> None:
    unschedule_at = _index(SOURCE, "cron.unschedule(")
    downgrade_at = _index(SOURCE, "def downgrade() -> None:")
    guard_at = _index(SOURCE, 'if _extension_installed("pg_cron"):', start=downgrade_at)
    assert downgrade_at < guard_at < unschedule_at
