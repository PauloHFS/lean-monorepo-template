"""Autorização ABAC — ÚNICA fonte de verdade das permissões da API.

Regras:
- Nenhum endpoint decide permissão com `if user.is_superuser`; ele chama
  `can()` / `authorize()` / `require()` daqui.
- Cada `Action` tem uma política: função pura `(Subject, Resource | None) -> bool`
  sobre atributos do usuário (quem é), do recurso (de quem é) e do ambiente.
- Leituras em lote usam `scope_for()`, que traduz a mesma política num filtro
  SQL, para o banco só devolver linhas permitidas (sem duplicar a regra).
- Permissões são estáticas e vivem no código (revisáveis em PR); tabela/JSON só
  se um dia houver edição dinâmica de papéis.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from fastapi import HTTPException

from app.api.deps import CurrentUser


class Subject(Protocol):
    """Atributos do usuário usados pelas políticas."""

    id: UUID
    is_superuser: bool
    is_active: bool


class Action(StrEnum):
    USERS_LIST = "users:list"
    USERS_DELETE = "users:delete"
    USERS_ENQUEUE_EMAIL = "users:enqueue_email"


@dataclass(frozen=True, slots=True)
class Resource:
    """Atributos do recurso alvo. Para usuários, `owner_id` é o próprio usuário."""

    owner_id: UUID | None = None


Policy = Callable[[Subject, Resource | None], bool]


def _admin_only(user: Subject, _res: Resource | None) -> bool:
    return user.is_active and user.is_superuser


def _owner_or_admin(user: Subject, res: Resource | None) -> bool:
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    return res is not None and res.owner_id == user.id


POLICIES: dict[Action, Policy] = {
    Action.USERS_LIST: _admin_only,
    Action.USERS_ENQUEUE_EMAIL: _admin_only,
    Action.USERS_DELETE: _owner_or_admin,
}


def can(user: Subject, action: Action, resource: Resource | None = None) -> bool:
    """Deny-by-default: ação sem política cadastrada é negada."""
    policy = POLICIES.get(action)
    return bool(policy and policy(user, resource))


def authorize(user: Subject, action: Action, resource: Resource | None = None) -> None:
    if not can(user, action, resource):
        raise HTTPException(status_code=403, detail="forbidden")


def require(action: Action) -> Callable[..., Awaitable[None]]:
    """Dependency para ações que não dependem de um recurso específico."""

    async def _dep(user: CurrentUser) -> None:
        authorize(user, action)

    return _dep


def scope_for(user: Subject) -> tuple[str, dict[str, Any]]:
    """Política → filtro SQL (`WHERE`) parametrizado para leituras em lote.

    Devolve `("TRUE", {})` quando o usuário enxerga tudo e uma condição restrita
    caso contrário; nunca interpola valores na string.
    """
    if not user.is_active:
        return "FALSE", {}
    if user.is_superuser:
        return "TRUE", {}
    return "id = :scope_uid", {"scope_uid": user.id}
