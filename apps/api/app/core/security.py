"""Segurança: hash de senha, tokens de sessão, helpers de cookie.

Decisões:
- Senhas: bcrypt (custo 12) via lib `bcrypt` direta (passlib está em
  manutenção e incompatível com bcrypt>=4.1).
- Sessões: tokens opacos (secrets.token_urlsafe) — guardamos apenas o hash
  em `sessions.token_hash`. Cookie envia o token cru.
- Cookies: HttpOnly, SameSite=Lax por padrão, Secure em prod.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt

from app.core.config import settings

_BCRYPT_ROUNDS = 12
_BCRYPT_MAX_PASSWORD_BYTES = 72  # limite do algoritmo


def _to_bytes(plain: str) -> bytes:
    # bcrypt trunca em 72 bytes internamente sem erro, mas prefiro truncar
    # explicitamente para evitar divergência entre hash e check em senhas com
    # caracteres multibyte (ex.: pt-BR com emoji).
    return plain.encode("utf-8")[:_BCRYPT_MAX_PASSWORD_BYTES]


def hash_password(plain: str) -> str:
    if len(plain) < settings.password_min_length:
        raise ValueError(
            f"senha deve ter ao menos {settings.password_min_length} caracteres"
        )
    return bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# --- Session tokens (opaque, não-JWT) ----------------------------------------
def generate_session_token() -> str:
    """Token cru que vai no cookie."""
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    """Hash SHA-256 do token — armazenamos isso no banco.

    SHA-256 (e não bcrypt) porque o token já tem 48 bytes de entropia
    e a tabela precisa de lookup O(1) no índice unique.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=settings.session_ttl_seconds)


# --- Cookie helpers ----------------------------------------------------------
def cookie_attrs() -> dict[str, Any]:
    return {
        "key": settings.session_cookie_name,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
        "max_age": settings.session_ttl_seconds,
    }


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(value=token, **cookie_attrs())


def clear_session_cookie(response) -> None:
    response.delete_cookie(**cookie_attrs())