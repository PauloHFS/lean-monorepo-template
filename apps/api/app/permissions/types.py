"""Vocabulário fechado da autorização: papéis, ações, recursos e o ator.

Tudo é `StrEnum`: o OpenAPI gera uniões literais no TypeScript, então o front
não consegue pedir uma ação/recurso que o backend desconhece (tipagem estrita
ponta a ponta).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

Scalar = str | int | bool | None


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Action(StrEnum):
    CREATE = "create"
    READ = "read"
    LIST = "list"
    UPDATE = "update"
    DELETE = "delete"


class Resource(StrEnum):
    USER = "user"
    EMAIL = "email"


@dataclass(frozen=True, slots=True)
class Actor:
    """Quem está agindo. Atributos expostos às regras: `id`, `role`, `is_active`."""

    id: UUID
    role: Role
    is_active: bool = True

    def attrs(self) -> dict[str, Scalar]:
        return {"id": str(self.id), "role": self.role.value, "is_active": self.is_active}


def actor_from_user(user: Any) -> Actor:
    """Papel derivado de `users.is_superuser` (admin | member).

    Para ganhar papéis novos (manager, guest…): coluna `role` + migration, um
    valor novo em `Role` e as regras em `rules.py` — nada mais muda.
    """
    uid = user.id
    is_super = bool(getattr(user, "is_superuser", False))
    is_act = bool(getattr(user, "is_active", True))
    return Actor(
        id=cast(UUID, uid),
        role=Role.ADMIN if is_super else Role.MEMBER,
        is_active=is_act,
    )
