"""UserOut aceita tanto ORM (User) quanto dict row do SQLAlchemy Core."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.api.schemas import UserOut
from app.db.models.user import User


def test_userout_model_validate_from_orm() -> None:
    uid = uuid4()
    user = User(
        id=uid,
        email="a@b.com",
        password_hash="x",
        full_name="A",
        is_active=True,
        is_superuser=False,
    )

    out = UserOut.model_validate(user)

    assert out.id == uid
    assert out.email == "a@b.com"


def test_userout_from_dict_row() -> None:
    uid = uuid4()
    row: dict[str, Any] = {
        "id": uid,
        "email": "a@b.com",
        "full_name": None,
        "is_active": True,
        "is_superuser": False,
    }

    out = UserOut(**row)

    assert out.id == uid
