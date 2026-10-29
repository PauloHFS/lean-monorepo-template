"""Serviço de usuários — ÚNICO caminho para ler/mutar `users`.

Rotas, CLI e jobs chamam estas funções; cada uma autoriza (`authorize*`) e, nas
leituras em lote, empurra a política para o banco (`to_sql`). Nenhuma outra
camada decide permissão.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import UserOut
from app.core.logging import get_logger
from app.permissions import Action, Actor, Resource, authorize, authorize_class, to_sql
from app.permissions.types import Scalar
from app.services.errors import NotFoundError

log = get_logger("users")

# `__SCOPE__` é substituído pelo predicado compilado da política (ver sql.py).
_LIST_SQL = """
SELECT id, email, full_name, is_active, is_superuser
  FROM users
 WHERE __SCOPE__
 ORDER BY created_at DESC
 LIMIT :lim OFFSET :off
"""

# Estático: cada coluna só muda se o flag `set_*` vier (PATCH parcial sem SQL dinâmico).
_UPDATE_SQL = text(
    """
UPDATE users
   SET full_name    = CASE WHEN :set_full_name    THEN CAST(:full_name AS text)     ELSE full_name END,
       is_active    = CASE WHEN :set_is_active    THEN CAST(:is_active AS boolean)  ELSE is_active END,
       is_superuser = CASE WHEN :set_is_superuser THEN CAST(:is_superuser AS boolean) ELSE is_superuser END,
       updated_at   = now()
 WHERE id = :id
RETURNING id, email, full_name, is_active, is_superuser
"""
)

_UPDATABLE = ("full_name", "is_active", "is_superuser")


async def list_users(
    session: AsyncSession, actor: Actor, *, limit: int, offset: int
) -> list[UserOut]:
    authorize_class(actor, Action.LIST, Resource.USER)
    scope = to_sql(actor, Action.READ, Resource.USER)
    rows = (
        (
            await session.execute(
                scope.query(_LIST_SQL), {**scope.params, "lim": limit, "off": offset}
            )
        )
        .mappings()
        .all()
    )
    return [UserOut.model_validate(dict(r)) for r in rows]


async def update_user(
    session: AsyncSession, actor: Actor, user_id: UUID, changes: dict[str, Scalar]
) -> UserOut:
    unknown = set(changes) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"campos não atualizáveis: {sorted(unknown)}")
    authorize(actor, Action.UPDATE, Resource.USER, {"id": user_id}, fields=changes.keys())

    params: dict[str, Scalar] = {"id": str(user_id)}
    for column in _UPDATABLE:
        params[f"set_{column}"] = column in changes
        params[column] = changes.get(column)
    row = (await session.execute(_UPDATE_SQL, params)).mappings().first()
    if row is None:
        raise NotFoundError("user")
    await session.commit()
    log.info(
        "users.update",
        actor_id=str(actor.id),
        target_id=str(user_id),
        fields=sorted(changes),
    )
    return UserOut.model_validate(dict(row))


async def delete_user(session: AsyncSession, actor: Actor, user_id: UUID) -> None:
    authorize(actor, Action.DELETE, Resource.USER, {"id": user_id})
    res = cast(
        CursorResult[Any],
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id}),
    )
    await session.commit()
    if not res.rowcount:
        raise NotFoundError("user")
