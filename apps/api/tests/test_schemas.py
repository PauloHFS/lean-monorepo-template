"""Tests de schemas Pydantic — round-trip de serialização."""
import pytest
from pydantic import ValidationError

from app.api.schemas import UserOut


def test_userout_full():
    u = UserOut(id="u-1", email="a@b.com", full_name="A", is_active=True, is_superuser=False)
    assert u.email == "a@b.com"
    assert u.full_name == "A"
    assert u.is_active is True


def test_userout_is_active_is_required():
    with pytest.raises(ValidationError):
        UserOut(id="u-1", email="a@b.com", full_name=None, is_superuser=False)  # type: ignore[call-arg]


def test_userout_email_validated():
    with pytest.raises(ValidationError):
        UserOut(id="u-1", email="not-an-email", full_name=None, is_active=True, is_superuser=False)