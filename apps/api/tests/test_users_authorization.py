"""Rotas de users exigem superuser (AD-008: sem banco)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.dependencies.utils import get_dependant, request_params_to_args
from fastapi.routing import APIRoute

from app.api.v1.endpoints.users import delete_user, require_superuser, router


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
    user = SimpleNamespace(id=UUID("00000000-0000-0000-0000-000000000001"), is_superuser=False)
    with pytest.raises(HTTPException) as exc:
        await delete_user(
            UUID("00000000-0000-0000-0000-000000000002"),
            cast(Any, user),
            _fake_session(rowcount=1),
        )

    assert exc.value.status_code == 403


async def test_delete_user_returns_404_when_nothing_was_deleted() -> None:
    user = SimpleNamespace(id=UUID("00000000-0000-0000-0000-000000000001"), is_superuser=True)
    with pytest.raises(HTTPException) as exc:
        await delete_user(
            UUID("00000000-0000-0000-0000-000000000002"),
            cast(Any, user),
            _fake_session(rowcount=0),
        )

    assert exc.value.status_code == 404


async def test_delete_user_owner_succeeds() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    user = SimpleNamespace(id=user_id, is_superuser=False)

    assert await delete_user(user_id, cast(Any, user), _fake_session(rowcount=1)) is None
