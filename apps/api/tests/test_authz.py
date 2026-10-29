"""Política ABAC central (app.core.authz)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.authz import Action, Resource, authorize, can, scope_for


@dataclass
class U:
    id: UUID
    is_superuser: bool = False
    is_active: bool = True


def test_admin_can_do_everything() -> None:
    admin = U(uuid4(), is_superuser=True)
    assert all(can(admin, a, Resource(owner_id=uuid4())) for a in Action)


def test_regular_user_only_deletes_self() -> None:
    me, other = U(uuid4()), uuid4()
    assert can(me, Action.USERS_DELETE, Resource(owner_id=me.id))
    assert not can(me, Action.USERS_DELETE, Resource(owner_id=other))
    assert not can(me, Action.USERS_DELETE)


def test_regular_user_cannot_list_or_send_email() -> None:
    me = U(uuid4())
    assert not can(me, Action.USERS_LIST)
    assert not can(me, Action.USERS_ENQUEUE_EMAIL)


def test_inactive_user_is_denied_even_if_superuser() -> None:
    ghost = U(uuid4(), is_superuser=True, is_active=False)
    assert not any(can(ghost, a, Resource(owner_id=ghost.id)) for a in Action)


def test_authorize_raises_403() -> None:
    with pytest.raises(HTTPException) as exc:
        authorize(U(uuid4()), Action.USERS_LIST)
    assert exc.value.status_code == 403


def test_scope_for_translates_policy_to_sql_filter() -> None:
    admin, me = U(uuid4(), is_superuser=True), U(uuid4())
    assert scope_for(admin) == ("TRUE", {})
    assert scope_for(me) == ("id = :scope_uid", {"scope_uid": me.id})
    assert scope_for(U(uuid4(), is_active=False)) == ("FALSE", {})
