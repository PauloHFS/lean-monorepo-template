"""TOTP (RFC 6238) para 2FA.

Fluxo:
1. setup()    — gera secret, criptografa com Fernet, persiste (mas NÃO ativa).
2. confirm()  — valida primeiro código. Se OK, marca enabled, retorna 10 recovery codes.
3. verify()   — valida código durante login. Aceita também recovery code.

O secret NUNCA é devolvido após confirm() — é criptografado em repouso.
A criptografia usa `cryptography.fernet.Fernet` com chave derivada do SECRET_KEY.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string

import pyotp
from cryptography.fernet import Fernet

from app.core import cache
from app.core.config import settings

_SECRET_BYTES = 20  # 160 bits, padrão RFC 6238
_ISSUER = "Lean Monorepo"
_RECOVERY_CODE_COUNT = 10


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def generate_secret() -> str:
    """Secret TOTP em base32 (pronto pra QR / Google Authenticator)."""
    # pyotp.random_base32 exige len >= 32 (160 bits codificados), então codificamos
    # diretamente os bytes secretos em base32.
    return base64.b32encode(secrets.token_bytes(_SECRET_BYTES)).decode("ascii").rstrip("=")


def encrypt_secret(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode("ascii"))


def decrypt_secret(token: bytes) -> str:
    return _fernet().decrypt(token).decode("ascii")


def provisioning_uri(secret: str, account: str) -> str:
    """URI `otpauth://` que o cliente converte em QR."""
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=_ISSUER)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Compara `code` contra o TOTP atual. `valid_window=1` aceita ±30s."""
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


# --- Recovery codes ----------------------------------------------------------
_RECOVERY_ALPHABET = string.ascii_lowercase + string.digits
_RECOVERY_LENGTH = 10


def generate_recovery_codes(n: int = _RECOVERY_CODE_COUNT) -> list[str]:
    """Códigos de 10 chars alfanuméricos. Uso único."""
    return [
        "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
        for _ in range(n)
    ]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


# --- 2FA pending state -------------------------------------------------------
# O usuário loga com senha OK; se tem 2FA, devolvemos requires_2fa=true
# e gravamos um "pending" no cache com TTL curto. O próximo /2fa/verify
# consome esse pending e completa o login.
_PENDING_TTL_S = 300  # 5 min para completar o 2FA


async def store_pending(user_id: str, *, ip: str | None, ua: str | None) -> str:
    token = secrets.token_urlsafe(24)
    payload = json.dumps({"user_id": user_id, "ip": ip, "ua": ua})
    await cache.set(f"2fa:pending:{token}", payload, ttl_s=_PENDING_TTL_S)
    return token


async def consume_pending(token: str) -> dict | None:
    raw = await cache.get(f"2fa:pending:{token}")
    if raw is None:
        return None
    await cache.delete(f"2fa:pending:{token}")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw