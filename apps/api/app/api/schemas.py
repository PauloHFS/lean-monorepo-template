"""Schemas Pydantic compartilhados.

Centraliza os modelos de entrada/saída usados em mais de um endpoint —
gera um OpenAPI limpo e tipos TS coerentes no front.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_superuser: bool


class UserUpdateIn(BaseModel):
    """PATCH parcial: só os campos enviados mudam (e só os que a política libera)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    is_superuser: bool | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> UserUpdateIn:
        if not self.model_fields_set:
            raise ValueError("informe ao menos um campo")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: bool


class OkOut(BaseModel):
    ok: bool
