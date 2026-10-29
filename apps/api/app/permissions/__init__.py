"""Permissões ABAC — fonte única de verdade (regras em `rules.py`).

Fluxo: rota → serviço (`app/services/*`) → `authorize()`/`to_sql()` daqui.
Rotas não contêm lógica de autorização; o front consome `export_policy()`.
"""

from app.permissions.engine import (
    PermissionDenied,
    allowed_fields,
    authorize,
    authorize_class,
    can,
    can_class,
    redact,
)
from app.permissions.manifest import PolicyOut, export_policy
from app.permissions.sql import SqlFilter, to_sql
from app.permissions.types import Action, Actor, Resource, Role, actor_from_user

__all__ = [
    "Action",
    "Actor",
    "PermissionDenied",
    "PolicyOut",
    "Resource",
    "Role",
    "SqlFilter",
    "actor_from_user",
    "allowed_fields",
    "authorize",
    "authorize_class",
    "can",
    "can_class",
    "export_policy",
    "redact",
    "to_sql",
]
