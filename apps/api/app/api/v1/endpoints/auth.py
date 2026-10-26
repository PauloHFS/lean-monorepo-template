"""Auth: registro, login, logout, /me."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AfterValidator, BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser
from app.api.schemas import UserOut
from app.core import totp as totp_mod
from app.core.config import settings
from app.core.logging import get_logger
from app.core.ratelimit import enforce_account_limit, rate_limit
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    clear_session_cookie,
    generate_session_token,
    hash_password,
    hash_session_token,
    session_expiry,
    set_session_cookie,
    verify_password,
)

router = APIRouter()
log = get_logger("auth")


def _email_fingerprint(email: str) -> str:
    """sha256 curto do e-mail normalizado — nunca logamos o endereço cru."""
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _max_72_utf8_bytes(value: str) -> str:
    """bcrypt só considera 72 bytes; rejeitar aqui evita truncamento silencioso."""
    if len(value.encode("utf-8")) > 72:
        raise ValueError("senha deve ter no máximo 72 bytes UTF-8")
    return value


# min_length vem de settings (não hardcode) para não divergir de hash_password;
# max_length=72 em caracteres é o teto do bcrypt, e o AfterValidator garante o
# teto em BYTES (um caractere multibyte pode ocupar mais de um byte).
# Settings valida password_min_length <= 72 no boot (fail-fast).
Password = Annotated[
    str,
    Field(min_length=settings.password_min_length, max_length=72),
    AfterValidator(_max_72_utf8_bytes),
]


class RegisterIn(BaseModel):
    email: EmailStr
    password: Password
    full_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: Password


class LoginOut(BaseModel):
    """Resposta de login: ou UserOut (login OK) ou challenge de 2FA pendente."""

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
    await enforce_account_limit("register", payload.email, limit=3, window_s=3600)
    ph = hash_password(payload.password)
    try:
        row = (
            (
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
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(400, "could not create user")
        await session.commit()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="email already registered") from None
    log.info(
        "auth.register",
        outcome="success",
        email_fp=_email_fingerprint(payload.email),
        user_id=str(row["id"]),
    )
    return UserOut(**dict(row))


@router.post(
    "/login",
    response_model=LoginOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit("auth.login", limit=5, window_s=60))],
)
async def login(payload: LoginIn, request: Request, response: Response, session: DB) -> LoginOut:
    await enforce_account_limit("login", payload.email, limit=10, window_s=300)
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, email, password_hash, full_name, is_superuser, is_active, totp_enabled "
                    "FROM users WHERE email = :e"
                ),
                {"e": payload.email},
            )
        )
        .mappings()
        .first()
    )

    email_fp = _email_fingerprint(payload.email)
    if not row:
        # Mesmo custo do caminho com usuário: não revela existência da conta.
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        log.warning("auth.login", outcome="failure", reason="unknown_email", email_fp=email_fp)
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not verify_password(payload.password, row["password_hash"]):
        log.warning("auth.login", outcome="failure", reason="invalid_password", email_fp=email_fp)
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not row["is_active"]:
        log.warning(
            "auth.login",
            outcome="failure",
            reason="inactive",
            email_fp=email_fp,
            user_id=str(row["id"]),
        )
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

    log.info(
        "auth.login",
        outcome="success",
        email_fp=email_fp,
        user_id=str(row["id"]),
        requires_2fa=bool(methods),
    )

    if methods:
        # Não emite cookie ainda — guarda pending e pede verificação
        token = await totp_mod.store_pending(
            str(row["id"]),
            ip=request.client.host if request.client else None,
            ua=request.headers.get("user-agent"),
        )
        return LoginOut(
            requires_2fa=True,
            pending_token=token,
            methods=methods,
            user=None,
        )

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
    return LoginOut(
        requires_2fa=False,
        user=UserOut(
            id=row["id"],
            email=row["email"],
            full_name=row["full_name"],
            is_active=row["is_active"],
            is_superuser=row["is_superuser"],
        ),
    )


@router.post("/logout", status_code=204, response_model=None)
async def logout(request: Request, response: Response, session: DB) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await session.execute(
            text("DELETE FROM sessions WHERE token_hash = :th"),
            {"th": hash_session_token(token)},
        )
        await session.commit()
    log.info("auth.logout", outcome="success" if token else "no_session")
    clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
