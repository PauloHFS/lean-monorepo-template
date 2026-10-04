"""Tests do rate limit (sem DB: SQL e factory)."""
import inspect

from app.core.ratelimit import HIT_SQL, rate_limit


def test_hit_sql_uses_upsert_and_returns_count():
    assert "INSERT INTO rate_limits" in HIT_SQL
    assert "ON CONFLICT (key) DO UPDATE" in HIT_SQL
    assert "RETURNING count" in HIT_SQL
    # Janela deve ser resetada condicionalmente
    assert "window_start <" in HIT_SQL
    assert "window_start = CASE" in HIT_SQL


def test_hit_sql_does_not_interpolate_key():
    """A chave deve ir como parâmetro, nunca interpolada (anti-SQLi)."""
    assert ":key" in HIT_SQL
    assert "'" not in HIT_SQL.split("ON CONFLICT (key)")[0].split("VALUES")[1].split(",")[0]


def test_rate_limit_factory_returns_callable_with_request():
    dep = rate_limit("test.endpoint", limit=3, window_s=10)
    assert callable(dep)
    sig = inspect.signature(dep)
    assert "request" in sig.parameters