"""Auth: registro, login, logout, /me."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from app.api.deps import DB, CurrentUser
from app.api.schemas import UserOut
from app.core import totp as totp_mod
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    clear_session_cookie,
    generate_session_token,
    hash_password,
    hash_session_token,
    session_expiry,
    set_session_cookie,
    verify_password,
)

router = APIRouter()


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    """Resposta de login: ou UserOut (login OK) ou TwoFactorRequired (2FA pendente)."""
    requires_2fa: bool = False
    pending_token: str | None = None
    methods: list[str] = []

    user: UserOut | None = None


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("auth.register", limit=10, window_s=60))],
)
async def register(payload: RegisterIn, session: DB) -> UserOut:
    ph = hash_password(payload.password)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO users (email, password_hash, full_name)
                VALUES (:email, :ph, :name)
                RETURNING id, email, full_name, is_active, is_superuser
                """
            ),
            {"email": payload.email, "ph": ph, "name": payload.full_name},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(400, "could not create user")
    await session.commit()
    return UserOut(**dict(row))


@router.post(
    "/login",
    dependencies=[Depends(rate_limit("auth.login", limit=5, window_s=60))],
)
async def login(
    payload: LoginIn, request: Request, response: Response, session: DB
) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT id, email, password_hash, full_name, is_superuser, is_active, totp_enabled "
                "FROM users WHERE email = :e"
            ),
            {"e": payload.email},
        )
        .mappings()
        .first()
    )

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="user inactive")

    # Detecta métodos 2FA habilitados
    methods: list[str] = []
    if row["totp_enabled"]:
        methods.append("totp")
    pk = await session.execute(
        text("SELECT 1 FROM user_passkeys WHERE user_id = :uid LIMIT 1"),
        {"uid": row["id"]},
    )
    if pk.scalar_one_or_none():
        methods.append("passkey")

    if methods:
        # Não emite cookie ainda — guarda pending e pede verificação
        token = await totp_mod.store_pending(
            str(row["id"]),
            ip=request.client.host if request.client else None,
            ua=request.headers.get("user-agent"),
        )
        return {
            "requires_2fa": True,
            "pending_token": token,
            "methods": methods,
            "user": None,
        }

    # Sem 2FA → emite cookie direto
    token = generate_session_token()
    await session.execute(
        text(
            """
            INSERT INTO sessions (user_id, token_hash, user_agent, ip, expires_at)
            VALUES (:uid, :th, :ua, :ip, :exp)
            """
        ),
        {
            "uid": row["id"],
            "th": hash_session_token(token),
            "ua": request.headers.get("user-agent"),
            "ip": request.client.host if request.client else None,
            "exp": session_expiry(),
        },
    )
    await session.commit()

    set_session_cookie(response, token)
    return {
        "requires_2fa": False,
        "user": {
            "id": str(row["id"]),
            "email": row["email"],
            "full_name": row["full_name"],
            "is_active": row["is_active"],
            "is_superuser": row["is_superuser"],
        },
    }


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: DB) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await session.execute(
            text("DELETE FROM sessions WHERE token_hash = :th"),
            {"th": hash_session_token(token)},
        )
        await session.commit()
    clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)