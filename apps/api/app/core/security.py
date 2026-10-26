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
from starlette.responses import Response

from app.core.config import settings

_BCRYPT_ROUNDS = 12
_BCRYPT_MAX_PASSWORD_BYTES = 72  # limite do algoritmo

# Hash fixo (custo 12) de uma senha que ninguém usa. O login verifica contra
# ele quando o e-mail não existe, para que o tempo de resposta não revele
# quais contas existem.
DUMMY_PASSWORD_HASH = "$2b$12$YM4r8RAaojI.SGGBY1ZN6uNYfbeYBjeObw7w4hX.D8OB646N2BD/6"


def _to_bytes(plain: str) -> bytes:
    encoded = plain.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"senha excede {_BCRYPT_MAX_PASSWORD_BYTES} bytes UTF-8")
    return encoded


def hash_password(plain: str) -> str:
    if len(plain) < settings.password_min_length:
        raise ValueError(f"senha deve ter ao menos {settings.password_min_length} caracteres")
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


def _cookie_delete_attrs() -> dict[str, Any]:
    """Atributos aceitos por `Response.delete_cookie` (sem `max_age`).

    O starlette já envia `Max-Age=0` e uma expiração no passado; passar
    `max_age` aqui estoura `TypeError`.
    """
    return {
        "key": settings.session_cookie_name,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(value=token, **cookie_attrs())


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(**_cookie_delete_attrs())
