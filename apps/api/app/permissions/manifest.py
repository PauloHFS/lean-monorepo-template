"""Exporta a política do ator para o frontend (mesma regra, mesmo significado).

O front NÃO reimplementa permissões: baixa estas regras (já filtradas pelo papel
do ator) e as avalia com o interpretador de `src/lib/permissions`, validado
contra o Python por um arquivo de conformance compartilhado (`conformance.py`).
Mostrar/esconder UI é conveniência; quem impõe é sempre o backend.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.permissions.conditions import Cond
from app.permissions.rules import RULES
from app.permissions.types import Action, Actor, Resource, Role


class ActorOut(BaseModel):
    id: UUID
    role: Role


class RuleOut(BaseModel):
    resource: Resource
    action: Action
    fields: list[str] | None
    when: Cond


class PolicyOut(BaseModel):
    actor: ActorOut
    rules: list[RuleOut]


def export_policy(actor: Actor) -> PolicyOut:
    rules = (
        [
            RuleOut(
                resource=r.resource,
                action=r.action,
                fields=None if r.fields is None else sorted(r.fields),
                when=r.when,
            )
            for r in RULES
            if actor.role in r.roles
        ]
        if actor.is_active
        else []
    )
    return PolicyOut(actor=ActorOut(id=actor.id, role=actor.role), rules=rules)
