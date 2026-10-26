"""Rate limit por conta e o wiring de login/registro (sem Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.endpoints import auth
from app.core import ratelimit


def test_build_account_key_normalizes_case() -> None:
    assert ratelimit.build_account_key("login", "User@Example.COM") == (
        "acct:login:user@example.com"
    )


async def test_enforce_account_limit_uses_existing_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    async def _hit(key: str, *, limit: int, window_s: int) -> tuple[int, datetime]:
        calls.update(key=key, limit=limit, window_s=window_s)
        return 1, datetime.now(UTC)

    monkeypatch.setattr(ratelimit, "hit", _hit)

    await ratelimit.enforce_account_limit("login", "A@B.com", limit=10, window_s=300)

    assert calls == {"key": "acct:login:a@b.com", "limit": 10, "window_s": 300}


async def test_enforce_account_limit_raises_429(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _hit(_key: str, *, limit: int, window_s: int) -> tuple[int, datetime]:
        return limit + 1, datetime.now(UTC)

    monkeypatch.setattr(ratelimit, "hit", _hit)

    with pytest.raises(HTTPException) as exc_info:
        await ratelimit.enforce_account_limit("register", "a@b.com", limit=3, window_s=3600)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "rate limit exceeded"
    assert exc_info.value.headers == {"Retry-After": "3600"}


class _Mappings:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Mappings:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row


class _Session:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self._row = row

    async def execute(self, *_args: Any, **_kwargs: Any) -> _Mappings:
        return _Mappings(self._row)

    async def commit(self) -> None:
        return None


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": None})


async def test_login_enforces_10_per_300s_per_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, int, int]] = []

    async def _enforce(scope: str, account: str, *, limit: int, window_s: int) -> None:
        calls.append((scope, account, limit, window_s))

    monkeypatch.setattr(auth, "enforce_account_limit", _enforce)

    with pytest.raises(HTTPException) as exc_info:
        await auth.login(
            auth.LoginIn(email="user@example.com", password="correct horse"),
            _request(),
            Response(),
            _Session(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 401
    assert calls == [("login", "user@example.com", 10, 300)]


async def test_register_enforces_3_per_3600s_per_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, int, int]] = []

    async def _enforce(scope: str, account: str, *, limit: int, window_s: int) -> None:
        calls.append((scope, account, limit, window_s))

    monkeypatch.setattr(auth, "enforce_account_limit", _enforce)
    uid = uuid4()
    session = _Session(
        {
            "id": uid,
            "email": "user@example.com",
            "full_name": None,
            "is_active": True,
            "is_superuser": False,
        }
    )

    out = await auth.register(
        auth.RegisterIn(email="user@example.com", password="correct horse"),
        session,  # type: ignore[arg-type]
    )

    assert out.id == uid
    assert calls == [("register", "user@example.com", 3, 3600)]
