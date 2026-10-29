"""Rotas de users exigem superuser (AD-008: sem banco)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.dependencies.utils import get_dependant, request_params_to_args
from fastapi.routing import APIRoute

from app.api.v1.endpoints.users import delete_user, router
from app.permissions import Actor, PermissionDenied, Role
from app.services.errors import NotFoundError


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


def test_list_users_declares_authz_dependency() -> None:
    assert _dependency_calls(_route("GET", ""))


def test_enqueue_email_declares_authz_dependency() -> None:
    assert _dependency_calls(_route("POST", "/enqueue-email"))


def _path_param_result(value: str) -> tuple[Any, Any]:
    dependant = get_dependant(path="/users/{user_id}", call=delete_user)
    return request_params_to_args(dependant.path_params, {"user_id": value})


def test_delete_user_rejects_malformed_uuid_on_the_boundary() -> None:
    # FastAPI converte os erros de validação de path param em 422 antes de
    # chegar no handler (antes era cast do Postgres → 500).
    values, errors = _path_param_result("not-a-uuid")
    assert not values
    assert errors
    assert errors[0]["loc"] == ("path", "user_id")
    assert errors[0]["type"] == "uuid_parsing"


def test_delete_user_accepts_uuid_path_param() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    values, errors = _path_param_result(str(user_id))
    assert not errors
    assert values == {"user_id": user_id}


def _fake_session(rowcount: int) -> Any:
    async def execute(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(rowcount=rowcount)

    async def commit() -> None:
        return None

    return SimpleNamespace(execute=execute, commit=commit)


async def test_delete_user_forbids_other_regular_user() -> None:
    actor = Actor(id=UUID("00000000-0000-0000-0000-000000000001"), role=Role.MEMBER, is_active=True)
    with pytest.raises(PermissionDenied):
        await delete_user(
            UUID("00000000-0000-0000-0000-000000000002"),
            actor,
            _fake_session(rowcount=1),
        )


async def test_delete_user_returns_404_when_nothing_was_deleted() -> None:
    actor = Actor(id=UUID("00000000-0000-0000-0000-000000000001"), role=Role.ADMIN, is_active=True)
    with pytest.raises(NotFoundError):
        await delete_user(
            UUID("00000000-0000-0000-0000-000000000002"),
            actor,
            _fake_session(rowcount=0),
        )


async def test_delete_user_owner_succeeds() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    actor = Actor(id=user_id, role=Role.MEMBER, is_active=True)

    assert await delete_user(user_id, actor, _fake_session(rowcount=1)) is None
