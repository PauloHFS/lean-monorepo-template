"""Schemas Pydantic compartilhados.

Centraliza os modelos de entrada/saída usados em mais de um endpoint —
gera um OpenAPI limpo e tipos TS coerentes no front.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_superuser: bool


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: bool