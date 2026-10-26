"""Users endpoints — exemplo de CRUD + dispatch de job."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from opentelemetry import trace
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import CursorResult, text

from app.api.deps import DB, CurrentUser
from app.api.schemas import UserOut
from app.core.observability import inject_trace_context
from app.core.ratelimit import rate_limit
from app.jobs.app import defer_job
from app.jobs.tasks.email import send_email

router = APIRouter()


def require_superuser(user: CurrentUser) -> None:
    """Mesma regra do delete: listar todos os usuários / enviar e-mail é só admin."""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="forbidden")


class EnqueueEmailIn(BaseModel):
    to: EmailStr
    subject: str = Field(max_length=200)
    body: str = Field(max_length=100_000)


class EnqueueEmailOut(BaseModel):
    job_id: int  # id do job no Procrastinate
    status: str


@router.get("", response_model=list[UserOut], dependencies=[Depends(require_superuser)])
async def list_users(
    session: DB,
    # Teto de 100 evita varredura/payload descontrolado num endpoint autenticado.
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[UserOut]:
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT id, email, full_name, is_active, is_superuser
                  FROM users
                 ORDER BY created_at DESC
                 LIMIT :lim OFFSET :off
                """
                ),
                {"lim": limit, "off": offset},
            )
        )
        .mappings()
        .all()
    )
    return [UserOut(**dict(r)) for r in rows]


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204, response_model=None)
async def delete_user(user_id: str, user: CurrentUser, session: DB) -> None:
    if str(user.id) != user_id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="forbidden")
    res = cast(
        CursorResult[Any],
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id}),
    )
    await session.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="not found")


@router.post(
    "/enqueue-email",
    response_model=EnqueueEmailOut,
    status_code=202,
    dependencies=[
        Depends(require_superuser),
        Depends(rate_limit("users.enqueue_email", limit=5, window_s=60)),
    ],
)
async def enqueue_email(payload: EnqueueEmailIn, user: CurrentUser) -> EnqueueEmailOut:
    """Enfileira um `email.send` na fila do Procrastinate (mesma task do worker/CLI)."""
    tracer = trace.get_tracer("lean.api")
    with tracer.start_as_current_span("email.enqueue"):
        job_payload = inject_trace_context(
            {"to": payload.to, "subject": payload.subject, "text": payload.body}
        )
        job_id = await defer_job(
            send_email,
            rate_limit_kind="email.send",
            rate_limit_key=f"user:{user.id}",
            rate_limit_limit=20,
            rate_limit_window_s=60,
            **job_payload,
        )
    return EnqueueEmailOut(job_id=job_id, status="queued")
