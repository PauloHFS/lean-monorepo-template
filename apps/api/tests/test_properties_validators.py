"""Propriedades dos validadores Pydantic (sem banco).

Os TODOs marcam dívidas de contrato que este lane apenas documenta — os
schemas de produção não são alterados aqui.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.api.schemas import UserOut
from app.api.v1.endpoints.auth import LoginIn, RegisterIn
from app.api.v1.endpoints.twofa import TotpConfirmIn
from app.api.v1.endpoints.users import EnqueueEmailIn

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


@given(st.emails(), st.text(alphabet=_ASCII, max_size=8))
@settings(max_examples=30)
def test_login_currently_accepts_short_passwords(email: str, password: str) -> None:
    # TODO: dívida — `LoginIn` não tem `min_length`; senha vazia/curta passa.
    # Corrigir no schema quando o contrato de login for revisado.
    assert LoginIn(email=email, password=password).password == password


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
def test_totp_confirm_currently_accepts_any_string(code: str) -> None:
    # TODO: dívida — `TotpConfirmIn.code` não valida formato/dígitos; hoje
    # aceita qualquer string. Corrigir no schema (ex.: `Field(pattern=r"^\d{6}$")`).
    assert TotpConfirmIn(code=code).code == code


@given(st.emails(), st.text(alphabet=_ASCII), st.text(alphabet=_ASCII))
@settings(max_examples=30)
def test_enqueue_email_currently_accepts_unbounded_strings(
    to: str, subject: str, body: str
) -> None:
    # TODO: dívida — `EnqueueEmailIn.subject`/`body` não têm max_length; hoje
    # qualquer string (inclusive vazia) passa. Definir limites no schema.
    model = EnqueueEmailIn(to=to, subject=subject, body=body)
    assert model.subject == subject
    assert model.body == body
