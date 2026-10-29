"""Users endpoints — rotas finas: validam entrada e delegam à camada de serviço.

Autorização NÃO vive aqui: está em `app/permissions` e é aplicada pelos serviços.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import DB, CurrentActor, CurrentUser
from app.api.schemas import UserOut, UserUpdateIn
from app.core.ratelimit import rate_limit
from app.services import outbound_email
from app.services import users as users_service

router = APIRouter()


class EnqueueEmailIn(BaseModel):
    to: EmailStr
    subject: str = Field(max_length=200)
    body: str = Field(max_length=100_000)


class EnqueueEmailOut(BaseModel):
    job_id: int  # id do job no Procrastinate
    status: str


@router.get("", response_model=list[UserOut])
async def list_users(
    actor: CurrentActor,
    session: DB,
    # Teto de 100 evita varredura/payload descontrolado num endpoint autenticado.
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[UserOut]:
    return await users_service.list_users(session, actor, limit=limit, offset=offset)


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID, payload: UserUpdateIn, actor: CurrentActor, session: DB
) -> UserOut:
    changes = payload.model_dump(exclude_unset=True)
    return await users_service.update_user(session, actor, user_id, changes)


@router.delete("/{user_id}", status_code=204, response_model=None)
async def delete_user(user_id: UUID, actor: CurrentActor, session: DB) -> None:
    await users_service.delete_user(session, actor, user_id)


@router.post(
    "/enqueue-email",
    response_model=EnqueueEmailOut,
    status_code=202,
    dependencies=[Depends(rate_limit("users.enqueue_email", limit=5, window_s=60))],
)
async def enqueue_email(payload: EnqueueEmailIn, actor: CurrentActor) -> EnqueueEmailOut:
    """Enfileira um `email.send` na fila do Procrastinate (mesma task do worker/CLI)."""
    job_id = await outbound_email.enqueue_email(
        actor, to=payload.to, subject=payload.subject, body=payload.body
    )
    return EnqueueEmailOut(job_id=job_id, status="queued")
