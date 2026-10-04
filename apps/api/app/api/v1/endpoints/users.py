"""Users endpoints — exemplo de CRUD + dispatch de job."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from app.api.deps import DB, CurrentUser
from app.api.schemas import UserOut

router = APIRouter()


class EnqueueEmailIn(BaseModel):
    to: EmailStr
    subject: str
    body: str


class EnqueueEmailOut(BaseModel):
    job_id: str
    status: str


@router.get("", response_model=list[UserOut])
async def list_users(_: CurrentUser, session: DB, limit: int = 50, offset: int = 0) -> list[UserOut]:
    rows = (
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
        .mappings()
        .all()
    )
    return [UserOut(**dict(r)) for r in rows]


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: str, user: CurrentUser, session: DB) -> None:
    if str(user.id) != user_id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="forbidden")
    res = await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await session.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="not found")


@router.post("/enqueue-email", response_model=EnqueueEmailOut, status_code=202)
async def enqueue_email(payload: EnqueueEmailIn, session: DB) -> EnqueueEmailOut:
    """Enfileira um `email.send` na tabela `background_jobs`."""
    job_id = (
        await session.execute(
            text(
                """
                INSERT INTO background_jobs (kind, payload)
                VALUES ('email.send', :payload::jsonb)
                RETURNING id
                """
            ),
            {"payload": payload.model_dump_json()},
        )
        .scalar_one()
    )
    await session.commit()
    return EnqueueEmailOut(job_id=str(job_id), status="queued")