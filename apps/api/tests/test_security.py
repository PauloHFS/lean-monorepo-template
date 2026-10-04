"""Tests unitários de funções puras. Não precisam de DB."""
import pytest

from app.core import security


def test_hash_password_enforces_min_length():
    with pytest.raises(ValueError):
        security.hash_password("short")


def test_hash_and_verify_password_roundtrip():
    h = security.hash_password("a-strong-password")
    assert h.startswith("$2")
    assert security.verify_password("a-strong-password", h) is True
    assert security.verify_password("wrong", h) is False


def test_hash_session_token_is_deterministic_and_hex():
    t = "abc.def_ghi"
    h1 = security.hash_session_token(t)
    h2 = security.hash_session_token(t)
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_generate_session_token_has_enough_entropy():
    t1 = security.generate_session_token()
    t2 = security.generate_session_token()
    assert t1 != t2
    assert len(t1) >= 64  # token_urlsafe(48) → ~64 chars