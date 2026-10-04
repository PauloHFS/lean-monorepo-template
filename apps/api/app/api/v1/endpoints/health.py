"""Health check — faz ping no banco para confirmar a stack toda."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.schemas import HealthResponse
from app.db.session import SessionLocal

router = APIRouter()


@router.get("", response_model=HealthResponse, summary="Deep health check (DB ping)")
async def healthz() -> HealthResponse:
    """200 quando o app + Postgres estão OK. 503 quando algo falha."""
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT 1 AS ok"))
        ok = result.scalar_one() == 1

    return HealthResponse(status="ok" if ok else "degraded", db=ok)