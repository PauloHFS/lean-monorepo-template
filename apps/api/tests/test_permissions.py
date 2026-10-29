"""Testes unitários do motor de permissões ABAC e geração de SQL."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.permissions import (
    Action,
    Actor,
    PermissionDenied,
    Resource,
    Role,
    allowed_fields,
    authorize,
    can,
    can_class,
    to_sql,
)
from app.permissions.conformance import render


def test_conformance_fixture_is_in_sync() -> None:
    current = Path(__file__).parent / "data" / "permissions_conformance.json"
    assert current.read_text() == render(), (
        "Fixture de conformance desatualizada! Rode `just permissions-conformance`."
    )


def test_actor_admin_can_all_resources() -> None:
    admin = Actor(id=uuid4(), role=Role.ADMIN)
    assert can_class(admin, Action.LIST, Resource.USER)
    assert can_class(admin, Action.CREATE, Resource.EMAIL)
    assert can(admin, Action.DELETE, Resource.USER, {"id": uuid4()})


def test_actor_member_cannot_list_users() -> None:
    member = Actor(id=uuid4(), role=Role.MEMBER)
    assert not can_class(member, Action.LIST, Resource.USER)
    assert not can(member, Action.LIST, Resource.USER)


def test_actor_member_can_read_and_delete_self_only() -> None:
    member_id = uuid4()
    member = Actor(id=member_id, role=Role.MEMBER)

    # Self
    assert can(member, Action.READ, Resource.USER, {"id": member_id})
    assert can(member, Action.DELETE, Resource.USER, {"id": member_id})

    # Other
    other_id = uuid4()
    assert not can(member, Action.READ, Resource.USER, {"id": other_id})
    assert not can(member, Action.DELETE, Resource.USER, {"id": other_id})


def test_field_level_permissions() -> None:
    member_id = uuid4()
    member = Actor(id=member_id, role=Role.MEMBER)
    other_id = uuid4()
    admin = Actor(id=uuid4(), role=Role.ADMIN)

    # Member can only update full_name on self
    assert allowed_fields(member, Action.UPDATE, Resource.USER, {"id": member_id}) == frozenset(
        {"full_name"}
    )
    authorize(member, Action.UPDATE, Resource.USER, {"id": member_id}, fields=["full_name"])

    with pytest.raises(PermissionDenied):
        authorize(
            member,
            Action.UPDATE,
            Resource.USER,
            {"id": member_id},
            fields=["full_name", "is_superuser"],
        )

    # Admin on other can update full_name, is_active, is_superuser
    admin_fields = allowed_fields(admin, Action.UPDATE, Resource.USER, {"id": other_id})
    assert admin_fields == frozenset({"full_name", "is_active", "is_superuser"})


def test_sql_pushdown_generation() -> None:
    member_id = uuid4()
    member = Actor(id=member_id, role=Role.MEMBER)
    admin = Actor(id=uuid4(), role=Role.ADMIN)

    member_filter = to_sql(member, Action.READ, Resource.USER)
    assert "id = CAST(:perm_" in member_filter.clause
    assert member_filter.params.get("perm_0") == str(member_id)

    admin_filter = to_sql(admin, Action.READ, Resource.USER)
    assert admin_filter.clause == "TRUE"
