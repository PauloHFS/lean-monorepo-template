"""2FA endpoints: TOTP + passkey + recovery codes."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import CursorResult, text
from webauthn import base64url_to_bytes

from app.api.deps import DB, CurrentUser
from app.core import totp as totp_mod
from app.core import webauthn as wa
from app.core.security import (
    generate_session_token,
    hash_session_token,
    session_expiry,
    set_session_cookie,
)
from app.db.session import SessionLocal

router = APIRouter(prefix="/2fa")


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------
class TotpSetupOut(BaseModel):
    secret: str  # base32, plain — UI ext nunca mais vê isso
    otpauth_uri: str


class TotpConfirmIn(BaseModel):
    # Confirmação de setup: aqui só vale TOTP de 6 dígitos.
    code: str = Field(pattern=r"^\d{6}$")


class TotpConfirmOut(BaseModel):
    enabled: bool
    recovery_codes: list[str]  # mostrado UMA vez


class TwoFactorVerifyIn(BaseModel):
    pending_token: str = Field(min_length=16, max_length=128)
    # TOTP (6 dígitos) OU recovery code (10 chars [a-z0-9]) — sem pattern fixo.
    code: str = Field(min_length=6, max_length=64)


class OkOut(BaseModel):
    ok: bool


@router.post("/totp/setup", response_model=TotpSetupOut)
async def totp_setup(user: CurrentUser, session: DB) -> TotpSetupOut:
    """Gera secret e armazena criptografado. NÃO MARCA enabled — isso é /confirm."""
    secret = totp_mod.generate_secret()
    encrypted = totp_mod.encrypt_secret(secret)
    await session.execute(
        text(
            """
            UPDATE users SET totp_secret_enc = :enc WHERE id = :id
            """
        ),
        {"enc": encrypted, "id": user.id},
    )
    await session.commit()
    return TotpSetupOut(
        secret=secret,
        otpauth_uri=totp_mod.provisioning_uri(secret, user.email),
    )


@router.post("/totp/confirm", response_model=TotpConfirmOut)
async def totp_confirm(payload: TotpConfirmIn, user: CurrentUser, session: DB) -> TotpConfirmOut:
    """Ativa 2FA após validar primeiro código. Devolve recovery codes (1× só)."""
    if user.totp_secret_enc is None:
        raise HTTPException(400, "totp setup not started")
    secret = totp_mod.decrypt_secret(user.totp_secret_enc)
    if not totp_mod.verify_totp(secret, payload.code):
        raise HTTPException(401, "invalid code")

    codes = totp_mod.generate_recovery_codes()
    await session.execute(
        text("UPDATE users SET totp_enabled = TRUE, totp_confirmed_at = now() WHERE id = :id"),
        {"id": user.id},
    )
    # Persistir codes hasheados
    for code in codes:
        await session.execute(
            text(
                """
                INSERT INTO totp_recovery_codes (user_id, code_hash)
                VALUES (:uid, :h)
                """
            ),
            {"uid": user.id, "h": totp_mod.hash_recovery_code(code)},
        )
    await session.commit()
    return TotpConfirmOut(enabled=True, recovery_codes=codes)


# ---------------------------------------------------------------------------
# Verificação após login parcial
# ---------------------------------------------------------------------------
@router.post("/verify", response_model=OkOut)
async def twofa_verify(payload: TwoFactorVerifyIn, request: Request, response: Response) -> OkOut:
    """Consome o pending token + valida TOTP/recovery. Emite cookie de sessão."""
    pending = await totp_mod.consume_pending(payload.pending_token)
    if pending is None:
        raise HTTPException(401, "pending token invalid or expired")

    user_id = pending["user_id"]

    async with SessionLocal() as session:
        async with session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT id, email, totp_secret_enc, totp_enabled, is_active "
                            "FROM users WHERE id = :id"
                        ),
                        {"id": user_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None or not row["is_active"]:
            raise HTTPException(401, "user inactive")
        if not row["totp_enabled"]:
            raise HTTPException(400, "2fa not enabled for this user")

        # Tenta TOTP primeiro
        secret = totp_mod.decrypt_secret(row["totp_secret_enc"])
        if totp_mod.verify_totp(secret, payload.code):
            user_ok = True
        else:
            # Senão tenta recovery code
            r = cast(
                CursorResult[Any],
                await session.execute(
                    text(
                        """
                        UPDATE totp_recovery_codes
                           SET used_at = now()
                         WHERE user_id = :uid AND code_hash = :h AND used_at IS NULL
                        """
                    ),
                    {"uid": row["id"], "h": totp_mod.hash_recovery_code(payload.code)},
                ),
            )
            await session.commit()
            user_ok = r.rowcount > 0

        if not user_ok:
            raise HTTPException(401, "invalid 2fa code")

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
    return OkOut(ok=True)


# ---------------------------------------------------------------------------
# Passkey (WebAuthn)
# ---------------------------------------------------------------------------
class PasskeyCredentialDescriptorOut(BaseModel):
    id: str  # base64url
    type: Literal["public-key"]


class PasskeyRpOut(BaseModel):
    name: str
    id: str


class PasskeyUserOut(BaseModel):
    id: str  # base64url
    name: str
    displayName: str


class PasskeyPubKeyCredParamOut(BaseModel):
    type: Literal["public-key"]
    alg: int


class PasskeyAuthenticatorSelectionOut(BaseModel):
    residentKey: str
    requireResidentKey: bool
    userVerification: str


class PasskeyRegistrationOptionsOut(BaseModel):
    """JSON de `navigator.credentials.create()` (shape real da lib webauthn)."""

    rp: PasskeyRpOut
    user: PasskeyUserOut
    challenge: str
    pubKeyCredParams: list[PasskeyPubKeyCredParamOut]
    timeout: int
    excludeCredentials: list[PasskeyCredentialDescriptorOut]
    authenticatorSelection: PasskeyAuthenticatorSelectionOut
    attestation: str


class PasskeyAuthenticationOptionsOut(BaseModel):
    """JSON de `navigator.credentials.get()` (shape real da lib webauthn)."""

    challenge: str
    timeout: int
    rpId: str
    allowCredentials: list[PasskeyCredentialDescriptorOut]
    userVerification: str


class PasskeyRegisterOptionsOut(BaseModel):
    options: PasskeyRegistrationOptionsOut
    challenge: str  # b64 — armazenar no cache pra completar


class PasskeyLoginOptionsOut(BaseModel):
    options: PasskeyAuthenticationOptionsOut
    challenge: str  # b64 — armazenar no cache pra completar


class PasskeyCredentialBase(BaseModel):
    id: str
    rawId: str
    type: Literal["public-key"]


class PasskeyRegistrationResponse(BaseModel):
    clientDataJSON: str
    attestationObject: str
    transports: list[str] | None = None


class PasskeyRegistrationCredential(PasskeyCredentialBase):
    response: PasskeyRegistrationResponse


class PasskeyAuthenticationResponse(BaseModel):
    clientDataJSON: str
    authenticatorData: str
    signature: str
    userHandle: str | None = None


class PasskeyAuthenticationCredential(PasskeyCredentialBase):
    response: PasskeyAuthenticationResponse


class PasskeyRegisterIn(BaseModel):
    # "challenge_b64:pending_token" (~77 chars); folga para variações.
    challenge: str = Field(min_length=8, max_length=1024)
    credential: PasskeyRegistrationCredential


class PasskeyLoginIn(BaseModel):
    # "challenge_b64:pending_token" (~77 chars); folga para variações.
    challenge: str = Field(min_length=8, max_length=1024)
    credential: PasskeyAuthenticationCredential


def _split_challenge(value: str) -> tuple[str, str]:
    """Separa o challenge do token de pending devolvido pelas options."""
    try:
        challenge_b64, pending_token = value.split(":", 1)
    except ValueError:
        raise HTTPException(400, "invalid challenge") from None
    if not challenge_b64 or not pending_token:
        raise HTTPException(400, "invalid challenge")
    return challenge_b64, pending_token


def _credential_id(credential: PasskeyCredentialBase) -> bytes:
    """Extrai o credential_id (bytes) da credencial enviada pelo browser."""
    return base64url_to_bytes(credential.id)


async def _consume_challenge(pending_token: str, challenge_b64: str) -> dict[str, Any]:
    """Consome o pending e confere que o challenge enviado é o armazenado."""
    pending = await totp_mod.consume_pending(pending_token)
    if pending is None:
        raise HTTPException(401, "pending invalid or expired")
    stored = pending.get("challenge")
    if not isinstance(stored, str) or stored != challenge_b64:
        raise HTTPException(400, "challenge mismatch")
    return pending


@router.post("/passkey/register/options", response_model=PasskeyRegisterOptionsOut)
async def passkey_register_options(
    user: CurrentUser, session: DB, request: Request
) -> PasskeyRegisterOptionsOut:
    """Gera options para `navigator.credentials.create()`."""
    existing = (
        (
            await session.execute(
                text("SELECT credential_id FROM user_passkeys WHERE user_id = :uid"),
                {"uid": user.id},
            )
        )
        .mappings()
        .all()
    )
    options, challenge_b64 = wa.registration_options(
        user_id=str(user.id),
        user_email=user.email,
        existing_keys=[r["credential_id"] for r in existing],
    )
    token = await totp_mod.store_pending(
        str(user.id),
        ip=request.client.host if request.client else None,
        ua=request.headers.get("user-agent"),
        challenge=challenge_b64,
    )
    return PasskeyRegisterOptionsOut(
        options=PasskeyRegistrationOptionsOut.model_validate(options),
        challenge=f"{challenge_b64}:{token}",
    )


@router.post("/passkey/register/verify", status_code=204, response_model=None)
async def passkey_register_verify(
    payload: PasskeyRegisterIn, user: CurrentUser, session: DB
) -> None:
    """Verifica attestation e persiste a credencial."""
    challenge_b64, pending_token = _split_challenge(payload.challenge)
    pending = await _consume_challenge(pending_token, challenge_b64)
    if str(pending.get("user_id")) != str(user.id):
        raise HTTPException(400, "challenge mismatch")
    info = wa.complete_registration(
        challenge_b64=challenge_b64,
        credential=payload.credential.model_dump(exclude_none=True),
    )
    await session.execute(
        text(
            """
            INSERT INTO user_passkeys
                (user_id, credential_id, public_key, sign_count, transports)
            VALUES (:uid, :cid, :pk, :sc, NULL)
            """
        ),
        {
            "uid": user.id,
            "cid": info["credential_id"],
            "pk": info["public_key"],
            "sc": info["sign_count"],
        },
    )
    await session.commit()


@router.post("/passkey/login/options", response_model=PasskeyLoginOptionsOut)
async def passkey_login_options(payload: PendingIn, session: DB) -> PasskeyLoginOptionsOut:
    """Gera options para `navigator.credentials.get()`."""
    pending = await totp_mod.consume_pending(payload.pending_token)
    if pending is None:
        raise HTTPException(401, "pending invalid")
    keys = (
        (
            await session.execute(
                text("SELECT credential_id FROM user_passkeys WHERE user_id = :uid"),
                {"uid": pending["user_id"]},
            )
        )
        .mappings()
        .all()
    )
    if not keys:
        raise HTTPException(400, "no passkeys registered")
    options, challenge_b64 = wa.authentication_options([r["credential_id"] for r in keys])
    # Novo pending atrelado ao mesmo user, agora carregando o challenge gerado.
    new_token = await totp_mod.store_pending(
        pending["user_id"],
        ip=pending.get("ip"),
        ua=pending.get("ua"),
        challenge=challenge_b64,
    )
    return PasskeyLoginOptionsOut(
        options=PasskeyAuthenticationOptionsOut.model_validate(options),
        challenge=f"{challenge_b64}:{new_token}",
    )


@router.post("/passkey/login/verify", response_model=OkOut)
async def passkey_login_verify(
    payload: PasskeyLoginIn, request: Request, response: Response
) -> OkOut:
    """Verifica assertion e emite cookie."""
    challenge_b64, pending_token = _split_challenge(payload.challenge)
    pending = await _consume_challenge(pending_token, challenge_b64)
    user_id = pending["user_id"]
    credential_id = _credential_id(payload.credential)

    async with SessionLocal() as session:
        async with session.begin():
            pk = (
                (
                    await session.execute(
                        text(
                            "SELECT credential_id, public_key, sign_count "
                            "FROM user_passkeys WHERE credential_id = :cid"
                        ),
                        {"cid": credential_id},
                    )
                )
                .mappings()
                .first()
            )
        if pk is None:
            raise HTTPException(401, "no passkey for user")

        new_sign_count = wa.complete_authentication(
            challenge_b64=challenge_b64,
            credential=payload.credential.model_dump(exclude_none=True),
            public_key=bytes(pk["public_key"]),
            sign_count=pk["sign_count"],
        )
        await session.execute(
            text(
                "UPDATE user_passkeys SET sign_count = :sc, last_used_at = now() "
                "WHERE credential_id = :cid"
            ),
            {"sc": new_sign_count, "cid": credential_id},
        )
        await session.commit()

        token = generate_session_token()
        await session.execute(
            text(
                """
                INSERT INTO sessions (user_id, token_hash, user_agent, ip, expires_at)
                VALUES (:uid, :th, :ua, :ip, :exp)
                """
            ),
            {
                "uid": user_id,
                "th": hash_session_token(token),
                "ua": request.headers.get("user-agent"),
                "ip": request.client.host if request.client else None,
                "exp": session_expiry(),
            },
        )
        await session.commit()

    set_session_cookie(response, token)
    return OkOut(ok=True)


class PendingIn(BaseModel):
    pending_token: str = Field(min_length=16, max_length=128)


# Funções expostas para auth.login saber se o user tem 2FA habilitado
async def user_two_factor_methods(user_id: str, session: DB) -> list[str]:
    methods: list[str] = []
    row = (
        (
            await session.execute(
                text("SELECT totp_enabled FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row and row["totp_enabled"]:
        methods.append("totp")
    pk = await session.execute(
        text("SELECT 1 FROM user_passkeys WHERE user_id = :uid LIMIT 1"),
        {"uid": user_id},
    )
    if pk.scalar_one_or_none():
        methods.append("passkey")
    return methods
