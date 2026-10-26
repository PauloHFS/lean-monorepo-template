"""Registro: sucesso devolve UserOut; email duplicado vira 409 (sem DB)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints.auth import RegisterIn, register


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row


class _Session:
    def __init__(self, row: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self._row = row
        self._exc = exc
        self.committed = False

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Result:
        if self._exc is not None:
            raise self._exc
        return _Result(self._row)

    async def commit(self) -> None:
        self.committed = True


def _payload() -> RegisterIn:
    return RegisterIn(email="a@b.com", password="correct horse battery")


async def test_register_returns_userout() -> None:
    uid = uuid4()
    row = {
        "id": uid,
        "email": "a@b.com",
        "full_name": "A",
        "is_active": True,
        "is_superuser": False,
    }
    session = _Session(row=row)

    out = await register(_payload(), session)  # type: ignore[arg-type]

    assert out.id == uid
    assert out.email == "a@b.com"
    assert session.committed is True


async def test_register_duplicate_email_raises_409() -> None:
    session = _Session(exc=IntegrityError("INSERT", {}, Exception("duplicate key")))

    with pytest.raises(HTTPException) as exc_info:
        await register(_payload(), session)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "email already registered"
    assert session.committed is False
