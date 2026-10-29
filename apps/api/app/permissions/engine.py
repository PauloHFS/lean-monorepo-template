"""Motor de avaliação: `can()` e amigos. Funções puras, sem I/O.

- `can(...)`       decisão sobre UMA instância (estrita: atributo ausente = nega).
- `can_class(...)` decisão grossa por papel/ação/recurso (menus, gates de rota).
                   NUNCA use para autorizar mutação de uma instância.
- `allowed_fields` granularidade de coluna (`None` = todas, vazio = nenhuma).
- `authorize*`     levantam `PermissionDenied` (o app traduz em 403).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from app.permissions.conditions import EvalContext, MissingAttributeError, evaluate
from app.permissions.rules import RULES, Rule
from app.permissions.types import Action, Actor, Resource, Scalar


class PermissionDenied(Exception):
    def __init__(self, action: Action, resource: Resource, reason: str = "forbidden") -> None:
        super().__init__(f"{action.value} {resource.value}: {reason}")
        self.action = action
        self.resource = resource
        self.reason = reason


def normalize(entity: Mapping[str, object] | None) -> dict[str, Scalar] | None:
    """UUID vira str: a mesma forma que o JSON entrega ao front e ao SQL."""
    if entity is None:
        return None
    out: dict[str, Scalar] = {}
    for key, value in entity.items():
        if isinstance(value, UUID):
            out[key] = str(value)
        elif value is None or isinstance(value, str | int | bool):
            out[key] = value
        else:
            raise TypeError(f"atributo de recurso não suportado: {key}={type(value).__name__}")
    return out


def role_rules(actor: Actor, action: Action, resource: Resource) -> list[Rule]:
    if not actor.is_active:
        return []
    return [
        r for r in RULES if r.resource == resource and r.action == action and actor.role in r.roles
    ]


def matching_rules(
    actor: Actor,
    action: Action,
    resource: Resource,
    entity: Mapping[str, object] | None = None,
    env: Mapping[str, Scalar] | None = None,
) -> list[Rule]:
    ctx = EvalContext(actor=actor.attrs(), resource=normalize(entity), env=env or {})
    matched: list[Rule] = []
    for rule in role_rules(actor, action, resource):
        try:
            if evaluate(rule.when, ctx):
                matched.append(rule)
        except MissingAttributeError:
            continue
    return matched


def can(
    actor: Actor,
    action: Action,
    resource: Resource,
    entity: Mapping[str, object] | None = None,
    env: Mapping[str, Scalar] | None = None,
) -> bool:
    return bool(matching_rules(actor, action, resource, entity, env))


def can_class(actor: Actor, action: Action, resource: Resource) -> bool:
    return bool(role_rules(actor, action, resource))


def allowed_fields(
    actor: Actor,
    action: Action,
    resource: Resource,
    entity: Mapping[str, object] | None = None,
    env: Mapping[str, Scalar] | None = None,
) -> frozenset[str] | None:
    rules = matching_rules(actor, action, resource, entity, env)
    if not rules:
        return frozenset()
    union: set[str] = set()
    for rule in rules:
        if rule.fields is None:
            return None
        union |= rule.fields
    return frozenset(union)


def authorize(
    actor: Actor,
    action: Action,
    resource: Resource,
    entity: Mapping[str, object] | None = None,
    *,
    fields: Iterable[str] | None = None,
    env: Mapping[str, Scalar] | None = None,
) -> None:
    """Exige `can(...)` e, se `fields` vier, que TODAS as colunas estejam liberadas."""
    if not can(actor, action, resource, entity, env):
        raise PermissionDenied(action, resource)
    if fields is None:
        return
    allowed = allowed_fields(actor, action, resource, entity, env)
    if allowed is None:
        return
    denied = sorted(set(fields) - allowed)
    if denied:
        raise PermissionDenied(action, resource, f"fields not allowed: {', '.join(denied)}")


def authorize_class(actor: Actor, action: Action, resource: Resource) -> None:
    if not can_class(actor, action, resource):
        raise PermissionDenied(action, resource)


def redact(
    actor: Actor,
    resource: Resource,
    entity: Mapping[str, object],
    data: Mapping[str, Scalar],
) -> dict[str, Scalar]:
    """Leitura por coluna: devolve de `data` só os campos que `read` libera."""
    allowed = allowed_fields(actor, Action.READ, resource, entity)
    if allowed is None:
        return dict(data)
    return {k: v for k, v in data.items() if k in allowed}
