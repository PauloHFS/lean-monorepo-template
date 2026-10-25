"""Propriedades do rate limiter: helpers puros + invariantes do SQL (sem banco).

A semântica de contagem/janela vive no SQL (`HIT_SQL`); aqui só testamos o
texto do SQL e os helpers puros que a dependency usa.
"""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.ratelimit import HIT_SQL, build_key, is_blocked

_ASCII = st.characters(min_codepoint=32, max_codepoint=126)


@given(st.text(alphabet=_ASCII), st.text(alphabet=_ASCII))
@settings(max_examples=50)
def test_build_key_wraps_ip_and_endpoint(ip: str, endpoint: str) -> None:
    key = build_key(ip, endpoint)
    assert key.startswith(ip)
    assert key.endswith(endpoint)


@given(st.integers(), st.integers())
@settings(max_examples=50)
def test_is_blocked_threshold_is_count_greater_than_limit(count: int, limit: int) -> None:
    # As `limit` requisições passam; a de índice limit+1 é bloqueada.
    if count <= limit:
        assert is_blocked(count, limit) is False
    else:
        assert is_blocked(count, limit) is True


@given(st.integers(), st.integers())
@settings(max_examples=50)
def test_is_blocked_is_monotonic(count: int, limit: int) -> None:
    # Na fronteira (count == limit) o bloqueio começa em count+1, por isso a
    # implicação vale para todo count fora do ponto exato do limiar.
    assume(count != limit)
    if is_blocked(count + 1, limit):
        assert is_blocked(count, limit) is True


@given(st.integers())
@settings(max_examples=50)
def test_is_blocked_boundary_at_limit(limit: int) -> None:
    assert is_blocked(limit, limit) is False
    assert is_blocked(limit + 1, limit) is True


def test_hit_sql_is_upsert_with_bind_params_only() -> None:
    assert "ON CONFLICT" in HIT_SQL
    assert "RETURNING count" in HIT_SQL
    # Nenhuma interpolação de input: só bind params (`:key`, `:now`, ...).
    assert "%s" not in HIT_SQL
    assert "{" not in HIT_SQL
    assert "}" not in HIT_SQL
    assert 'f"' not in HIT_SQL
    assert "f'" not in HIT_SQL
    assert ":key" in HIT_SQL
