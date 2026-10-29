"""Compilador regra → SQL ("database pushdown").

Traduz as regras aplicáveis a (ator, ação, recurso) num predicado `WHERE`
parametrizado, para o banco devolver só linhas permitidas — sem carregar tudo em
memória e sem reescrever filtro à mão em cada query.

Segurança: nenhum valor entra no SQL como texto. Identificadores vêm da
whitelist `RESOURCE_COLUMNS`; valores (ator/ambiente/literais) viram bind params
`:perm_N`. Subárvores só com ator/ambiente/literais são resolvidas em tempo de
compilação (constant folding), então `TRUE`/`FALSE` sem tocar no banco.

Este arquivo é o ÚNICO lugar autorizado a montar SQL dinâmico (ver `SqlFilter.query`
e a exceção em `semgrep.yml`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import TextClause, text

from app.permissions.conditions import (
    AllOf,
    Always,
    AnyOf,
    CondNode,
    Eq,
    Lit,
    MissingAttributeError,
    Not,
    Ref,
)
from app.permissions.engine import role_rules
from app.permissions.rules import RESOURCE_COLUMNS, Column
from app.permissions.types import Action, Actor, Resource, Scalar

SCOPE_MARKER = "__SCOPE__"
_ALIAS_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_TRUE = "TRUE"
_FALSE = "FALSE"


@dataclass(frozen=True, slots=True)
class SqlFilter:
    clause: str
    params: dict[str, Scalar] = field(default_factory=lambda: {})

    def query(self, template: str) -> TextClause:
        """Injeta o predicado no lugar de `__SCOPE__` de um template LITERAL.

        Bind params: passe `self.params` junto com os seus no `execute`.
        """
        if template.count(SCOPE_MARKER) != 1:
            raise ValueError(f"o template precisa conter {SCOPE_MARKER} exatamente uma vez")
        return text(template.replace(SCOPE_MARKER, self.clause))


@dataclass(frozen=True, slots=True)
class _Val:
    value: Scalar


class _Compiler:
    def __init__(
        self,
        resource: Resource,
        actor: Actor,
        env: Mapping[str, Scalar],
        alias: str | None,
    ) -> None:
        if alias is not None and not _ALIAS_RE.match(alias):
            raise ValueError("alias SQL inválido")
        self.resource = resource
        self.actor_attrs = actor.attrs()
        self.env = env
        self.alias = alias
        self.params: dict[str, Scalar] = {}

    def _col(self, column: Column) -> str:
        return f"{self.alias}.{column.name}" if self.alias else column.name

    def _operand(self, op: Ref | Lit) -> Column | _Val:
        if isinstance(op, Lit):
            return _Val(op.value)
        if op.scope == "resource":
            column = RESOURCE_COLUMNS[self.resource].get(op.attr)
            if column is None:
                raise MissingAttributeError(f"resource.{op.attr}")
            return column
        bag = self.actor_attrs if op.scope == "actor" else self.env
        if op.attr not in bag:
            raise MissingAttributeError(f"{op.scope}.{op.attr}")
        return _Val(bag[op.attr])

    def _bind(self, value: Scalar) -> str:
        name = f"perm_{len(self.params)}"
        self.params[name] = value
        return name

    def _eq(self, left: Ref | Lit, right: Ref | Lit) -> str:
        a, b = self._operand(left), self._operand(right)
        if isinstance(a, _Val) and isinstance(b, _Val):
            return _TRUE if a.value == b.value else _FALSE
        if isinstance(a, Column) and isinstance(b, Column):
            return f"{self._col(a)} = {self._col(b)}"
        column, val = (a, b) if isinstance(a, Column) else (b, a)
        assert isinstance(column, Column)
        assert isinstance(val, _Val)
        if val.value is None:
            return f"{self._col(column)} IS NULL"
        name = self._bind(val.value)
        return f"{self._col(column)} = CAST(:{name} AS {column.sql_type})"

    def compile(self, cond: CondNode) -> str:  # noqa: PLR0911
        if isinstance(cond, Always):
            return _TRUE
        if isinstance(cond, Eq):
            return self._eq(cond.left, cond.right)
        if isinstance(cond, Not):
            inner = self.compile(cond.cond)
            if inner == _TRUE:
                return _FALSE
            if inner == _FALSE:
                return _TRUE
            return f"(NOT {inner})"
        parts = [self.compile(c) for c in cond.conds]
        if isinstance(cond, AllOf):
            if _FALSE in parts:
                return _FALSE
            rest = [p for p in parts if p != _TRUE]
            return _join(rest, " AND ", empty=_TRUE)
        assert isinstance(cond, AnyOf)
        if _TRUE in parts:
            return _TRUE
        rest = [p for p in parts if p != _FALSE]
        return _join(rest, " OR ", empty=_FALSE)


def _join(parts: list[str], sep: str, *, empty: str) -> str:
    if not parts:
        return empty
    if len(parts) == 1:
        return parts[0]
    return "(" + sep.join(parts) + ")"


def to_sql(
    actor: Actor,
    action: Action,
    resource: Resource,
    *,
    env: Mapping[str, Scalar] | None = None,
    alias: str | None = None,
) -> SqlFilter:
    """Predicado `WHERE` equivalente a `can(...)` linha a linha. Sem regra → `FALSE`."""
    compiler = _Compiler(resource, actor, env or {}, alias)
    fragments: list[str] = []
    for rule in role_rules(actor, action, resource):
        try:
            fragment = compiler.compile(rule.when)
        except MissingAttributeError:
            continue
        if fragment == _TRUE:
            return SqlFilter(_TRUE)
        if fragment != _FALSE:
            fragments.append(fragment)
    clause = _join(fragments, " OR ", empty=_FALSE)
    used = {k: v for k, v in compiler.params.items() if f":{k} " in f"{clause} "}
    return SqlFilter(clause, used)
