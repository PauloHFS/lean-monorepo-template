"""DSL declarativa de condições (o "A" de ABAC).

Uma condição é DADO, não função: o mesmo objeto é (1) avaliado em Python
(`evaluate`), (2) compilado para SQL (`sql.py`) e (3) serializado em JSON para o
frontend avaliar com o mesmo significado (`src/lib/permissions`). É isso que
mantém backend, banco e UI sem divergência.

Operandos referenciam atributos do **ator**, do **recurso** (a entidade-alvo) ou
do **ambiente** (ex.: hora UTC), ou são literais.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.permissions.types import Scalar

Scope = Literal["actor", "resource", "env"]


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True)


class Ref(_Node):
    kind: Literal["ref"] = "ref"
    scope: Scope
    attr: str


class Lit(_Node):
    kind: Literal["lit"] = "lit"
    value: Scalar


Operand = Annotated[Ref | Lit, Field(discriminator="kind")]


class Always(_Node):
    kind: Literal["always"] = "always"


class Eq(_Node):
    kind: Literal["eq"] = "eq"
    left: Operand
    right: Operand


class Not(_Node):
    kind: Literal["not"] = "not"
    cond: Cond


class AllOf(_Node):
    kind: Literal["all"] = "all"
    conds: tuple[Cond, ...]


class AnyOf(_Node):
    kind: Literal["any"] = "any"
    conds: tuple[Cond, ...]


CondNode = Always | Eq | Not | AllOf | AnyOf
Cond = Annotated[CondNode, Field(discriminator="kind")]

for _model in (Not, AllOf, AnyOf):
    _model.model_rebuild()


# ----------------------------------------------------------------------------
# Construtores (as regras em rules.py ficam legíveis)
# ----------------------------------------------------------------------------
ALWAYS = Always()


def actor(attr: str) -> Ref:
    return Ref(scope="actor", attr=attr)


def res(attr: str) -> Ref:
    return Ref(scope="resource", attr=attr)


def env(attr: str) -> Ref:
    return Ref(scope="env", attr=attr)


def lit(value: Scalar) -> Lit:
    return Lit(value=value)


def eq(left: Ref | Lit, right: Ref | Lit) -> Eq:
    return Eq(left=left, right=right)


def ne(left: Ref | Lit, right: Ref | Lit) -> Not:
    return Not(cond=eq(left, right))


def not_(cond: CondNode) -> Not:
    return Not(cond=cond)


def all_of(*conds: CondNode) -> AllOf:
    return AllOf(conds=conds)


def any_of(*conds: CondNode) -> AnyOf:
    return AnyOf(conds=conds)


# ----------------------------------------------------------------------------
# Avaliação em memória
# ----------------------------------------------------------------------------
class MissingAttributeError(LookupError):
    """Atributo referenciado ausente: a regra NÃO se aplica (deny-by-default)."""


@dataclass(frozen=True, slots=True)
class EvalContext:
    actor: Mapping[str, Scalar]
    resource: Mapping[str, Scalar] | None
    env: Mapping[str, Scalar]


def resolve(operand: Ref | Lit, ctx: EvalContext) -> Scalar:
    if isinstance(operand, Lit):
        return operand.value
    bag: Mapping[str, Scalar] | None
    if operand.scope == "actor":
        bag = ctx.actor
    elif operand.scope == "resource":
        bag = ctx.resource
    else:
        bag = ctx.env
    if bag is None or operand.attr not in bag:
        raise MissingAttributeError(f"{operand.scope}.{operand.attr}")
    return bag[operand.attr]


def evaluate(cond: CondNode, ctx: EvalContext) -> bool:
    if isinstance(cond, Always):
        return True
    if isinstance(cond, Eq):
        return resolve(cond.left, ctx) == resolve(cond.right, ctx)
    if isinstance(cond, Not):
        return not evaluate(cond.cond, ctx)
    if isinstance(cond, AllOf):
        return all(evaluate(c, ctx) for c in cond.conds)
    return any(evaluate(c, ctx) for c in cond.conds)
