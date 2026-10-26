"""Rotas de users exigem superuser (AD-008: sem banco)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.api.v1.endpoints.users import require_superuser, router


def _route(method: str, path: str) -> APIRoute:
    for route in router.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and route.methods is not None
            and method in route.methods
        ):
            return route
    raise AssertionError(f"rota {method} {path} não encontrada")


def _dependency_calls(route: APIRoute) -> list[Any]:
    return [dep.call for dep in route.dependant.dependencies]


def test_list_users_requires_superuser() -> None:
    assert require_superuser in _dependency_calls(_route("GET", ""))


def test_enqueue_email_requires_superuser() -> None:
    assert require_superuser in _dependency_calls(_route("POST", "/enqueue-email"))


def test_require_superuser_rejects_regular_user() -> None:
    with pytest.raises(HTTPException) as exc:
        require_superuser(cast(Any, SimpleNamespace(is_superuser=False)))

    assert exc.value.status_code == 403


def test_require_superuser_allows_admin() -> None:
    require_superuser(cast(Any, SimpleNamespace(is_superuser=True)))
