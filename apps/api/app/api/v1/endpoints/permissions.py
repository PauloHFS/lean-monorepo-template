"""Política do ator logado, para o frontend avaliar `can()` com as MESMAS regras."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentActor
from app.permissions import PolicyOut, export_policy

router = APIRouter()


@router.get("/me", response_model=PolicyOut)
async def my_policy(actor: CurrentActor) -> PolicyOut:
    return export_policy(actor)
