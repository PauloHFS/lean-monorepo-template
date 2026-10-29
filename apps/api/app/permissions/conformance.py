"""Vetores de conformance Python ↔ TypeScript.

Gera `apps/api/tests/data/permissions_conformance.json`: política exportada por
papel + casos com a resposta esperada calculada pelo motor Python. O pytest
confere que o arquivo está atualizado; o `node --test` do front confere que o
interpretador TS produz as mesmas respostas. Se alguém mudar uma regra ou um
interpretador, um dos dois testes quebra.

Regenerar: `just permissions-conformance`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.permissions.conditions import (
    ALWAYS,
    CondNode,
    EvalContext,
    MissingAttributeError,
    actor,
    all_of,
    any_of,
    env,
    eq,
    evaluate,
    lit,
    ne,
    not_,
    res,
)
from app.permissions.engine import allowed_fields, authorize, can, can_class
from app.permissions.manifest import export_policy
from app.permissions.types import Action, Actor, Resource, Role

ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")
MEMBER_ID = UUID("00000000-0000-0000-0000-000000000002")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000003")

_ACTORS = {
    "admin": Actor(id=ADMIN_ID, role=Role.ADMIN),
    "member": Actor(id=MEMBER_ID, role=Role.MEMBER),
}
_FIELD_CHECKS = (
    ["full_name"],
    ["is_active"],
    ["is_active", "is_superuser"],
    ["full_name", "is_active"],
)


def _entities(actor_id: UUID) -> list[dict[str, str] | None]:
    return [None, {"id": str(actor_id)}, {"id": str(OTHER_ID)}]


def _allowed(
    who: Actor, action: Action, resource: Resource, entity: dict[str, str] | None, fields: list[str]
) -> bool:
    try:
        authorize(who, action, resource, entity, fields=fields)
    except Exception:  # noqa: BLE001 - PermissionDenied é o único esperado
        return False
    return True


def _cond_case(
    name: str, cond: CondNode, ctx: Mapping[str, Mapping[str, Any] | None]
) -> dict[str, Any]:
    eval_ctx = EvalContext(actor=ctx["actor"] or {}, resource=ctx["resource"], env=ctx["env"] or {})
    try:
        expected: bool | str = evaluate(cond, eval_ctx)
    except MissingAttributeError:
        expected = "missing"
    return {"name": name, "cond": cond.model_dump(mode="json"), "ctx": ctx, "expected": expected}


def _condition_cases() -> list[dict[str, Any]]:
    a = {"id": "a1", "role": "member", "is_active": True}
    ctx = {"actor": a, "resource": {"id": "a1", "locked": False}, "env": {"hour_utc": 10}}
    other = {"actor": a, "resource": {"id": "b2", "locked": True}, "env": {"hour_utc": 23}}
    no_res = {"actor": a, "resource": None, "env": {}}
    return [
        _cond_case("always", ALWAYS, ctx),
        _cond_case("eq actor/resource true", eq(res("id"), actor("id")), ctx),
        _cond_case("eq actor/resource false", eq(res("id"), actor("id")), other),
        _cond_case("ne", ne(res("id"), actor("id")), other),
        _cond_case("eq literal", eq(actor("role"), lit("member")), ctx),
        _cond_case("eq bool literal", eq(res("locked"), lit(True)), other),
        _cond_case("eq env", eq(env("hour_utc"), lit(10)), ctx),
        _cond_case("not", not_(eq(res("locked"), lit(True))), ctx),
        _cond_case(
            "all", all_of(eq(res("id"), actor("id")), not_(eq(res("locked"), lit(True)))), ctx
        ),
        _cond_case(
            "all short", all_of(eq(res("id"), actor("id")), eq(res("locked"), lit(True))), ctx
        ),
        _cond_case(
            "any", any_of(eq(res("locked"), lit(True)), eq(env("hour_utc"), lit(23))), other
        ),
        _cond_case(
            "any none", any_of(eq(res("locked"), lit(True)), eq(env("hour_utc"), lit(1))), ctx
        ),
        _cond_case("missing resource", eq(res("id"), actor("id")), no_res),
        _cond_case("missing under not", ne(res("id"), actor("id")), no_res),
        _cond_case("missing env attr", eq(env("hour_utc"), lit(1)), no_res),
    ]


def build_conformance() -> dict[str, Any]:
    policies = {name: export_policy(who).model_dump(mode="json") for name, who in _ACTORS.items()}
    cases: list[dict[str, Any]] = []
    for name, who in _ACTORS.items():
        for action in Action:
            for resource in Resource:
                for entity in _entities(who.id):
                    fields = allowed_fields(who, action, resource, entity)
                    cases.append(
                        {
                            "actor": name,
                            "action": action.value,
                            "resource": resource.value,
                            "entity": entity,
                            "can": can(who, action, resource, entity),
                            "can_class": can_class(who, action, resource),
                            "fields": None if fields is None else sorted(fields),
                            "field_checks": [
                                {"fields": f, "ok": _allowed(who, action, resource, entity, f)}
                                for f in _FIELD_CHECKS
                            ],
                        }
                    )
    return {
        "version": 1,
        "policies": policies,
        "cases": cases,
        "condition_cases": _condition_cases(),
    }


def render() -> str:
    return json.dumps(build_conformance(), indent=2, ensure_ascii=False) + "\n"
