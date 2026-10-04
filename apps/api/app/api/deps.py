"""Dependências injetadas nos endpoints do FastAPI."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_session_token
from app.db.models.user import User
from app.db.session import get_db

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, session: DB) -> User:
    """Resolve o usuário a partir do cookie de sessão."""
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    sess_row = (
        await session.execute(
            text("SELECT id, user_id, expires_at FROM sessions WHERE token_hash = :th"),
            {"th": hash_session_token(token)},
        )
        .mappings()
        .first()
    )
    if not sess_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    if sess_row["expires_at"] < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expired session")

    # atualiza last_seen e commita — get_db não commita em saída sem erro
    await session.execute(
        text("UPDATE sessions SET last_seen = now() WHERE id = :id"),
        {"id": sess_row["id"]},
    )
    await session.commit()

    user = await session.get(User, sess_row["user_id"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]