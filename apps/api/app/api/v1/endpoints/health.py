"""Health checks em camadas.

- `livez`  (liveness): o processo está vivo e atendendo HTTP. Não toca no DB.
- `healthz` (readiness): o app está pronto para tráfego. Exige o Postgres.

Orquestradores devem reiniciar com base em `livez` (processo travado) e
remover do balanceamento com base em `healthz` (dependência fora).
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.schemas import HealthResponse
from app.db.session import SessionLocal

router = APIRouter()
livez_router = APIRouter()

# Teto do probe de readiness: DB lento não deve segurar o request.
DB_PROBE_TIMEOUT_S = 2.0


class LivenessOut(BaseModel):
    status: Literal["ok"] = "ok"


async def _db_ok() -> bool:
    """Probe isolado do DB (monkeypatchável nos testes)."""
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT 1 AS ok"))
        return result.scalar_one() == 1


@livez_router.get("", response_model=LivenessOut, summary="Liveness (process only)")
async def livez() -> LivenessOut:
    """200 enquanto o processo está vivo. Sem DB, sem dependências externas."""
    return LivenessOut()


@router.get("", response_model=HealthResponse, summary="Readiness (DB required)")
async def healthz(response: Response) -> HealthResponse:
    """200 quando o app + Postgres estão OK; 503 (degraded) caso contrário."""
    try:
        async with asyncio.timeout(DB_PROBE_TIMEOUT_S):
            ok = await _db_ok()
    except Exception:  # noqa: BLE001 — qualquer falha do DB degrada, não estoura 500
        ok = False

    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", db=False)

    return HealthResponse(status="ok", db=True)
