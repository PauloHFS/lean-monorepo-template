"""Validação de entrada dos schemas de request (fronteira de confiança, sem HTTP/DB)."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from annotated_types import Ge, Le
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints.auth import (
    EmailOtpRequestIn,
    EmailOtpVerifyIn,
    LoginIn,
    RegisterIn,
    validate_nist_password,
)
from app.api.v1.endpoints.twofa import (
    PasskeyLoginIn,
    PasskeyRegisterIn,
    PendingIn,
    TotpConfirmIn,
    TwoFactorVerifyIn,
)
from app.api.v1.endpoints.users import EnqueueEmailIn, list_users
from app.core.config import settings


# --- auth ---------------------------------------------------------------------
def test_register_rejects_password_below_settings_minimum() -> None:
    with pytest.raises(ValidationError):
        RegisterIn(email="a@b.com", password="x" * (settings.password_min_length - 1))


def test_register_accepts_password_at_minimum_and_at_72() -> None:
    assert RegisterIn(email="a@b.com", password="x" * settings.password_min_length)
    assert RegisterIn(email="a@b.com", password="x" * 72)


def test_register_rejects_password_above_72_chars() -> None:
    with pytest.raises(ValidationError):
        RegisterIn(email="a@b.com", password="x" * 73)


def test_register_rejects_full_name_above_200() -> None:
    with pytest.raises(ValidationError):
        RegisterIn(email="a@b.com", password="x" * 8, full_name="n" * 201)


def test_register_accepts_full_name_at_200() -> None:
    assert RegisterIn(email="a@b.com", password="x" * 8, full_name="n" * 200)


def test_login_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        LoginIn(email="a@b.com", password="")
    with pytest.raises(ValidationError):
        LoginIn(email="a@b.com", password="x" * (settings.password_min_length - 1))


def test_login_rejects_password_above_72_chars() -> None:
    with pytest.raises(ValidationError):
        LoginIn(email="a@b.com", password="x" * 100)


def test_register_rejects_multibyte_password_above_72_bytes() -> None:
    # 40 caracteres, mas 80 bytes em UTF-8: o limite é em bytes, não chars.
    with pytest.raises(ValidationError):
        RegisterIn(email="a@b.com", password="é" * 40)


def test_nist_password_rules_reject_common_and_repeated_and_email_match() -> None:
    for weak in ("12345678", "password", "aaaaaaaa", "user@example.com"):
        with pytest.raises(HTTPException) as exc:
            validate_nist_password(weak, "user@example.com")
        assert exc.value.status_code == 422

    # Senha forte passa sem erro
    validate_nist_password("c0rrect-h0rse-battery", "user@example.com")


def test_email_otp_schemas_validation() -> None:
    assert EmailOtpRequestIn(email="user@example.com")
    assert EmailOtpVerifyIn(email="user@example.com", code="012345")
    for bad in ("12345", "1234567", "abcdef"):
        with pytest.raises(ValidationError):
            EmailOtpVerifyIn(email="user@example.com", code=bad)


# --- 2FA ----------------------------------------------------------------------
def test_totp_confirm_accepts_six_digits_only() -> None:
    assert TotpConfirmIn(code="123456")
    for bad in ("12345", "1234567", "abcdef"):
        with pytest.raises(ValidationError):
            TotpConfirmIn(code=bad)


def test_two_factor_verify_accepts_totp_and_recovery_code() -> None:
    assert TwoFactorVerifyIn(pending_token="p" * 32, code="123456")
    assert TwoFactorVerifyIn(pending_token="p" * 32, code="a1b2c3d4e5")


def test_two_factor_verify_rejects_short_code() -> None:
    with pytest.raises(ValidationError):
        TwoFactorVerifyIn(pending_token="p" * 32, code="abc")


@pytest.mark.parametrize("token", ["p" * 15, "p" * 129])
def test_pending_token_length_bounds(token: str) -> None:
    with pytest.raises(ValidationError):
        TwoFactorVerifyIn(pending_token=token, code="123456")
    with pytest.raises(ValidationError):
        PendingIn(pending_token=token)


def test_pending_token_accepts_32_chars() -> None:
    assert PendingIn(pending_token="p" * 32)
    assert TwoFactorVerifyIn(pending_token="p" * 32, code="123456")


def test_passkey_challenge_length_bounds() -> None:
    # Só a constraint de tamanho é testável sem montar toda a credential.
    for model in (PasskeyRegisterIn, PasskeyLoginIn):
        field = model.model_fields["challenge"]
        assert field.metadata is not None
        assert _bound(field, "min_length") == 8
        assert _bound(field, "max_length") == 1024


# --- users --------------------------------------------------------------------
def test_enqueue_email_length_limits() -> None:
    assert EnqueueEmailIn(to="a@b.com", subject="s" * 200, body="b" * 100_000)
    with pytest.raises(ValidationError):
        EnqueueEmailIn(to="a@b.com", subject="s" * 201, body="b")
    with pytest.raises(ValidationError):
        EnqueueEmailIn(to="a@b.com", subject="s", body="b" * 100_001)


def _query_default(name: str) -> Any:
    return inspect.signature(list_users).parameters[name].default


def _bound(field: Any, name: str) -> int | None:
    for meta in field.metadata:
        value = getattr(meta, name, None)
        if isinstance(value, int):
            return value
    return None


def test_list_users_query_defaults_and_bounds() -> None:
    limit = _query_default("limit")
    offset = _query_default("offset")
    assert limit.default == 50
    assert offset.default == 0
    assert _bound(limit, "ge") == 1
    assert _bound(limit, "le") == 100
    assert _bound(offset, "ge") == 0
    # Confirma que as constraints vêm de annotated_types (não strings soltas).
    assert any(isinstance(m, Ge | Le) for m in limit.metadata)
