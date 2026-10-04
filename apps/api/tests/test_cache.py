"""Tests do cache (sem DB: SQL e a função de geração de password)."""
import string

from app.cli import _gen_password
from app.core.cache import DELETE_SQL, GET_SQL, UPSERT_SQL


def test_get_sql_filters_expired_rows():
    assert "WHERE key = :key" in GET_SQL
    assert "expires_at > :now" in GET_SQL
    # Permite cache sem expiração (expires_at IS NULL)
    assert "expires_at IS NULL" in GET_SQL


def test_upsert_sql_uses_jsonb_and_on_conflict():
    assert "INSERT INTO kv_cache" in UPSERT_SQL
    assert "::jsonb" in UPSERT_SQL
    assert "ON CONFLICT (key) DO UPDATE" in UPSERT_SQL
    assert "EXCLUDED.value" in UPSERT_SQL


def test_delete_sql_is_simple():
    assert DELETE_SQL.strip() == "DELETE FROM kv_cache WHERE key = :key"


def test_gen_password_length_and_alphabet():
    p = _gen_password(length=24)
    assert len(p) == 24
    assert all(c in string.ascii_letters + string.digits for c in p)


def test_gen_password_is_random():
    a = _gen_password(32)
    b = _gen_password(32)
    assert a != b