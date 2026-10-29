"""REGRAS — ÚNICA fonte de verdade das permissões.

Para mudar quem pode o quê, edite SÓ este arquivo (+ teste). Regras são
somente-permissivas (deny-by-default): sem regra aplicável, nega. Várias regras
aplicáveis se somam (OR; `fields` faz união).

Persistência: em código, de propósito. Permissões deste template são estáticas e
revisadas em PR; tabela/JSON só se um dia houver UI para editar papéis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.permissions.conditions import ALWAYS, Cond, actor, eq, ne, res
from app.permissions.types import Action, Resource, Role


class Rule(BaseModel):
    """Concede `action` sobre `resource` aos `roles` quando `when` for verdadeira.

    `fields`: colunas que a regra libera para `read`/`update`; `None` = todas.
    """

    model_config = ConfigDict(frozen=True)

    resource: Resource
    action: Action
    roles: frozenset[Role]
    when: Cond = ALWAYS
    fields: frozenset[str] | None = None


_ADMIN = frozenset({Role.ADMIN})
_MEMBER = frozenset({Role.MEMBER})
_IS_SELF = eq(res("id"), actor("id"))

RULES: tuple[Rule, ...] = (
    # --- user -------------------------------------------------------------
    Rule(resource=Resource.USER, action=Action.LIST, roles=_ADMIN),
    Rule(resource=Resource.USER, action=Action.READ, roles=_ADMIN),
    Rule(resource=Resource.USER, action=Action.READ, roles=_MEMBER, when=_IS_SELF),
    Rule(resource=Resource.USER, action=Action.DELETE, roles=_ADMIN),
    Rule(resource=Resource.USER, action=Action.DELETE, roles=_MEMBER, when=_IS_SELF),
    # Campos mutáveis (granularidade de coluna): todos editam o próprio nome;
    # admin edita o nome de qualquer um e promove/desativa OUTRAS contas — nunca
    # a si mesmo (evita "apagar o último admin" por engano).
    Rule(
        resource=Resource.USER,
        action=Action.UPDATE,
        roles=_MEMBER,
        when=_IS_SELF,
        fields=frozenset({"full_name"}),
    ),
    Rule(
        resource=Resource.USER,
        action=Action.UPDATE,
        roles=_ADMIN,
        fields=frozenset({"full_name"}),
    ),
    Rule(
        resource=Resource.USER,
        action=Action.UPDATE,
        roles=_ADMIN,
        when=ne(res("id"), actor("id")),
        fields=frozenset({"is_active", "is_superuser"}),
    ),
    # --- email (disparo de job) -------------------------------------------
    Rule(resource=Resource.EMAIL, action=Action.CREATE, roles=_ADMIN),
)


# ----------------------------------------------------------------------------
# Mapa recurso → colunas, para o compilador SQL (whitelist: só estes
# identificadores entram em SQL; o resto vira bind param).
# ----------------------------------------------------------------------------
SqlType = Literal["uuid", "boolean", "text", "integer"]


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    sql_type: SqlType


RESOURCE_COLUMNS: dict[Resource, dict[str, Column]] = {
    Resource.USER: {
        "id": Column("id", "uuid"),
        "is_active": Column("is_active", "boolean"),
        "is_superuser": Column("is_superuser", "boolean"),
    },
    Resource.EMAIL: {},
}
