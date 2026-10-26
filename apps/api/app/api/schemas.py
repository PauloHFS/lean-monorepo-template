"""Schemas Pydantic compartilhados.

Centraliza os modelos de entrada/saída usados em mais de um endpoint —
gera um OpenAPI limpo e tipos TS coerentes no front.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_superuser: bool


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: bool
