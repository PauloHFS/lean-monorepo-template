"""Testes da validação de Settings (sem Postgres, sem rede — AD-008)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("value", [8, 72])
def test_password_min_length_accepts_values_within_range(value: int) -> None:
    assert Settings(password_min_length=value).password_min_length == value


@pytest.mark.parametrize("value", [0, -1, 73, 80])
def test_password_min_length_rejects_values_above_schema_cap(value: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(password_min_length=value)

    message = str(exc_info.value)
    assert "PASSWORD_MIN_LENGTH" in message
    assert "72" in message
