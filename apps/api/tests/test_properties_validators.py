"""Propriedades dos validadores Pydantic (sem banco).

Os limites de tamanho/pattern dos schemas de request são as propriedades
exercitadas aqui (fronteira de confiança).
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.api.schemas import UserOut
from app.api.v1.endpoints.auth import LoginIn, RegisterIn
from app.api.v1.endpoints.twofa import TotpConfirmIn
from app.api.v1.endpoints.users import EnqueueEmailIn
from app.core.config import settings as app_settings

_ASCII = st.characters(min_codepoint=32, max_codepoint=126)
_INVALID_EMAILS = ["", "a@b", "not an email"]
_email_adapter: TypeAdapter[EmailStr] = TypeAdapter(EmailStr)


@given(st.emails())
@settings(max_examples=30)
def test_register_accepts_valid_email(email: str) -> None:
    model = RegisterIn(email=email, password="x" * 8)
    assert "@" in model.email


@given(st.sampled_from(_INVALID_EMAILS))
@settings(max_examples=10)
def test_register_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        RegisterIn(email=email, password="x" * 8)


@given(st.text(alphabet=_ASCII, max_size=7), st.emails())
@settings(max_examples=30)
def test_register_rejects_password_below_min_length(password: str, email: str) -> None:
    with pytest.raises(ValidationError):
        RegisterIn(email=email, password=password)


@given(st.emails())
@settings(max_examples=30)
def test_register_accepts_password_at_min_length(email: str) -> None:
    assert RegisterIn(email=email, password="x" * 8).password == "x" * 8


@given(
    st.emails(),
    st.text(alphabet=_ASCII, max_size=app_settings.password_min_length - 1),
)
@settings(max_examples=30)
def test_login_rejects_short_passwords(email: str, password: str) -> None:
    with pytest.raises(ValidationError):
        LoginIn(email=email, password=password)


@given(st.emails())
@settings(max_examples=30)
def test_emailstr_accepts_generated_emails(email: str) -> None:
    assert "@" in _email_adapter.validate_python(email)


@given(st.sampled_from(_INVALID_EMAILS))
@settings(max_examples=10)
def test_emailstr_rejects_obviously_invalid_strings(value: str) -> None:
    with pytest.raises(ValidationError):
        _email_adapter.validate_python(value)


@given(st.emails())
@settings(max_examples=30)
def test_user_out_accepts_valid_constructor(email: str) -> None:
    user = UserOut(
        id="u1",
        email=email,
        full_name=None,
        is_active=True,
        is_superuser=False,
    )
    assert "@" in user.email


@given(st.sampled_from(_INVALID_EMAILS))
@settings(max_examples=10)
def test_user_out_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        UserOut(id="u1", email=email, full_name=None, is_active=True, is_superuser=False)


@given(st.text(alphabet=_ASCII))
@settings(max_examples=30)
def test_totp_confirm_requires_six_digits(code: str) -> None:
    if re.fullmatch(r"\d{6}", code):
        assert TotpConfirmIn(code=code).code == code
    else:
        with pytest.raises(ValidationError):
            TotpConfirmIn(code=code)


@given(
    st.emails(),
    st.text(alphabet=_ASCII, max_size=200),
    st.text(alphabet=_ASCII, max_size=100_000),
)
@settings(max_examples=10)
def test_enqueue_email_accepts_within_limits(to: str, subject: str, body: str) -> None:
    model = EnqueueEmailIn(to=to, subject=subject, body=body)
    assert model.subject == subject
    assert model.body == body


@given(st.emails(), st.text(alphabet=_ASCII, min_size=201, max_size=220))
@settings(max_examples=5)
def test_enqueue_email_rejects_long_subject(to: str, subject: str) -> None:
    with pytest.raises(ValidationError):
        EnqueueEmailIn(to=to, subject=subject, body="")
