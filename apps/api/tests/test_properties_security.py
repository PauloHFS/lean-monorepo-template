"""Propriedades (Hypothesis) de segurança: senha, sessão e TOTP.

bcrypt custa ~100 ms/hash (custo 12), então toda propriedade que hasheia usa
`deadline=None` e `max_examples` pequeno para o suite não estourar.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pyotp
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core import security, totp
from app.core.config import settings as app_settings

# ASCII imprimível evita surpresas de encoding em `verify_password`, que faz
# `hashed.encode("ascii")`.
_ASCII = st.characters(min_codepoint=32, max_codepoint=126)


@given(st.text(alphabet=_ASCII, min_size=app_settings.password_min_length))
@settings(max_examples=10, deadline=None)
def test_password_roundtrip_and_hash_shape(plain: str) -> None:
    # Qualquer senha válida verificada contra o próprio hash passa; o hash não
    # é a senha e usa bcrypt custo 12.
    hashed = security.hash_password(plain)
    assert security.verify_password(plain, hashed) is True
    assert hashed != plain
    assert hashed.startswith("$2b$12$")


@given(st.text(alphabet=_ASCII, min_size=1))
@settings(max_examples=30, deadline=None)
def test_plaintext_is_never_a_valid_hash(value: str) -> None:
    # Texto puro não tem o formato de um hash bcrypt válido.
    assert security.verify_password(value, value) is False


@given(
    st.text(alphabet=_ASCII, min_size=app_settings.password_min_length, max_size=71),
    st.text(alphabet=_ASCII, min_size=1, max_size=71),
)
@settings(max_examples=10, deadline=None)
def test_wrong_password_is_rejected(plain: str, wrong: str) -> None:
    assume(plain != wrong)
    assert security.verify_password(wrong, security.hash_password(plain)) is False


@given(st.text(alphabet=_ASCII, min_size=73, max_size=120))
@settings(max_examples=10, deadline=None)
def test_bcrypt_rejects_passwords_above_72_bytes(plain: str) -> None:
    # O limite do bcrypt é explícito: hash rejeita >72 bytes e verify devolve
    # False (nunca trunca em silêncio).
    with pytest.raises(ValueError):
        security.hash_password(plain)
    assert security.verify_password(plain, security.hash_password(plain[:72])) is False


@given(st.text(alphabet=_ASCII, max_size=20))
@settings(max_examples=20, deadline=None)
def test_hash_password_raises_iff_below_min_length(plain: str) -> None:
    if len(plain) < app_settings.password_min_length:
        with pytest.raises(ValueError):
            security.hash_password(plain)
    else:
        assert security.verify_password(plain, security.hash_password(plain)) is True


@given(st.text(alphabet=_ASCII, min_size=1))
@settings(max_examples=50)
def test_hash_session_token_is_lowercase_hex_and_deterministic(token: str) -> None:
    first = security.hash_session_token(token)
    second = security.hash_session_token(token)
    assert first == second
    assert len(first) == 64
    assert all(c in "0123456789abcdef" for c in first)


@given(st.text(alphabet=_ASCII, min_size=1), st.text(alphabet=_ASCII, min_size=1))
@settings(max_examples=50)
def test_distinct_session_tokens_hash_differently(token_a: str, token_b: str) -> None:
    assume(token_a != token_b)
    assert security.hash_session_token(token_a) != security.hash_session_token(token_b)


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=20)
def test_generate_session_token_is_urlsafe_and_unique(_: int) -> None:
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    first = security.generate_session_token()
    second = security.generate_session_token()
    assert len(first) >= 48
    assert all(c in allowed for c in first)
    assert first != second


@given(st.datetimes())
@settings(max_examples=50)
def test_session_expiry_adds_exact_ttl(now: datetime) -> None:
    assert security.session_expiry(now) - now == timedelta(seconds=app_settings.session_ttl_seconds)


@given(st.integers())
@settings(max_examples=30)
def test_generate_secret_is_32_base32_chars(_: int) -> None:
    secret = totp.generate_secret()
    assert len(secret) == 32
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)


@given(st.text(alphabet=_ASCII))
@settings(max_examples=25)
def test_secret_encryption_roundtrip(secret: str) -> None:
    assert totp.decrypt_secret(totp.encrypt_secret(secret)) == secret


@given(st.text(alphabet=_ASCII, min_size=1))
@settings(max_examples=50)
def test_hash_recovery_code_is_lowercase_hex_and_deterministic(code: str) -> None:
    first = totp.hash_recovery_code(code)
    second = totp.hash_recovery_code(code)
    assert first == second
    assert len(first) == 64
    assert all(c in "0123456789abcdef" for c in first)


@given(st.integers(min_value=1, max_value=20))
@settings(max_examples=20)
def test_generate_recovery_codes_count_format_and_uniqueness(n: int) -> None:
    codes = totp.generate_recovery_codes(n)
    assert len(codes) == n
    assert len(set(codes)) == n
    for code in codes:
        assert len(code) == 10
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789" for c in code)


@given(st.integers(min_value=1, max_value=5))
@settings(max_examples=10, deadline=None)
def test_verify_totp_accepts_current_code_and_rejects_other_secret(_: int) -> None:
    secret = totp.generate_secret()
    other = totp.generate_secret()
    assume(secret != other)
    assert totp.verify_totp(secret, pyotp.TOTP(secret).now(), valid_window=0) is True
    assert totp.verify_totp(secret, pyotp.TOTP(other).now(), valid_window=0) is False
