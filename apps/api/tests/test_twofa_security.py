"""Testes de segurança dos endpoints 2FA (sem DB — AD-008).

Cobrem os três achados da lane A2:
- a passkey usada no login precisa pertencer ao user do pending;
- os endpoints sensíveis têm rate limit ligado;
- o pending token de login não pode ser trocado por challenge mais de uma vez.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.v1.endpoints import twofa
from app.core import ratelimit

_CLIENT_IP = "203.0.113.7"


def _route(path: str) -> Any:
    for route in twofa.router.routes:
        if getattr(route, "path", None) == path:
            return route
    raise AssertionError(f"rota {path} não encontrada")


def _request() -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "client": (_CLIENT_IP, 12345),
    }
    return Request(scope)


def _rate_limit_callables(route: Any) -> list[Callable[..., Awaitable[None]]]:
    callables: list[Callable[..., Awaitable[None]]] = []
    for dep in route.dependencies:
        if dep.dependency is not None:
            callables.append(cast(Callable[..., Awaitable[None]], dep.dependency))
    return callables


async def _call_dep(dep: Callable[..., Awaitable[None]]) -> None:
    await dep(_request())


# --- 1. Passkey scoped to the pending user ---------------------------------
def test_passkey_lookup_sql_filters_by_user() -> None:
    """Sem `user_id = :uid`, a passkey do atacante autentica a vítima (ATO)."""
    assert "credential_id = :cid" in twofa.PASSKEY_LOOKUP_SQL
    assert "user_id = :uid" in twofa.PASSKEY_LOOKUP_SQL
    # bind params, nunca interpolação
    assert ":cid" in twofa.PASSKEY_LOOKUP_SQL
    assert ":uid" in twofa.PASSKEY_LOOKUP_SQL


def test_passkey_update_sql_filters_by_user() -> None:
    assert "credential_id = :cid" in twofa.PASSKEY_UPDATE_SQL
    assert "user_id = :uid" in twofa.PASSKEY_UPDATE_SQL


# --- 2. Rate limit wired to sensitive endpoints -----------------------------
@pytest.mark.parametrize(
    ("path", "scope", "limit", "window_s"),
    [
        ("/2fa/verify", "2fa.verify", 10, 60),
        ("/2fa/passkey/login/options", "2fa.passkey.login.options", 20, 60),
        ("/2fa/passkey/login/verify", "2fa.passkey.login.verify", 20, 60),
        ("/2fa/passkey/passwordless/options", "2fa.passkey.passwordless.options", 20, 60),
        ("/2fa/passkey/passwordless/verify", "2fa.passkey.passwordless.verify", 20, 60),
    ],
)
def test_sensitive_endpoint_has_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    scope: str,
    limit: int,
    window_s: int,
) -> None:
    calls: list[tuple[str, int, int]] = []

    async def fake_hit(key: str, limit: int, window_s: int) -> tuple[int, Any]:
        calls.append((key, limit, window_s))
        return 1, None

    monkeypatch.setattr(ratelimit, "hit", fake_hit)

    deps = _rate_limit_callables(_route(path))
    assert deps, f"{path} sem dependency de rate limit"
    for dep in deps:
        asyncio.run(_call_dep(dep))

    assert calls == [(f"{_CLIENT_IP}:{scope}", limit, window_s)]


# --- 3. Pending token cannot be refreshed forever ---------------------------
def test_login_options_rejects_pending_that_already_has_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_consume(_token: str) -> dict[str, Any]:
        return {"user_id": "user-1", "challenge": "already-minted"}

    monkeypatch.setattr(twofa.totp_mod, "consume_pending", fake_consume)

    async def call() -> None:
        await twofa.passkey_login_options(twofa.PendingIn(pending_token="x" * 16), cast(Any, None))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(call())

    assert exc_info.value.status_code == 401
