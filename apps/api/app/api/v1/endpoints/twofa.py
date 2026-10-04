"""2FA endpoints: TOTP + passkey + recovery codes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

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
    code: str


class TotpConfirmOut(BaseModel):
    enabled: bool
    recovery_codes: list[str]  # mostrado UMA vez


class TwoFactorRequiredOut(BaseModel):
    requires_2fa: bool
    pending_token: str
    methods: list[str]  # ex.: ["totp", "passkey"]


class TwoFactorVerifyIn(BaseModel):
    pending_token: str
    code: str  # TOTP code OU recovery code


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
@router.post("/verify", response_model=None)
async def twofa_verify(payload: TwoFactorVerifyIn, request: Request, response: Response) -> dict:
    """Consome o pending token + valida TOTP/recovery. Emite cookie de sessão."""
    pending = await totp_mod.consume_pending(payload.pending_token)
    if pending is None:
        raise HTTPException(401, "pending token invalid or expired")

    user_id = pending["user_id"]

    async with SessionLocal() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT id, email, totp_secret_enc, totp_enabled, is_active "
                        "FROM users WHERE id = :id"
                    ),
                    {"id": user_id},
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
            r = await session.execute(
                text(
                    """
                    UPDATE totp_recovery_codes
                       SET used_at = now()
                     WHERE user_id = :uid AND code_hash = :h AND used_at IS NULL
                    """
                ),
                {"uid": row["id"], "h": totp_mod.hash_recovery_code(payload.code)},
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
    return {"ok": True}


# ---------------------------------------------------------------------------
# Passkey (WebAuthn)
# ---------------------------------------------------------------------------
class PasskeyOptionsOut(BaseModel):
    options: dict  # JSON que vai direto para navigator.credentials
    challenge: str  # b64 — armazenar no cache pra completar


class PasskeyRegisterIn(BaseModel):
    challenge: str  # b64 do setup
    client_data_b64: str
    attestation_b64: str


class PasskeyLoginIn(BaseModel):
    challenge: str
    client_data_b64: str
    authenticator_b64: str
    signature_b64: str
    credential_id_b64: str  # para localizar qual pubkey comparar


@router.post("/passkey/register/options", response_model=PasskeyOptionsOut)
async def passkey_register_options(user: CurrentUser, session: DB) -> PasskeyOptionsOut:
    """Gera options para `navigator.credentials.create()`."""
    existing = (
        await session.execute(
            text("SELECT credential_id FROM user_passkeys WHERE user_id = :uid"),
            {"uid": user.id},
        )
        .mappings()
        .all()
    )
    options, challenge_b64 = wa.registration_options(
        user_id=str(user.id), user_email=user.email, existing_keys=[r["credential_id"] for r in existing]
    )
    await totp_mod.store_pending(f"passkey:register:{user.id}", ip="", ua="")  # placeholder
    return PasskeyOptionsOut(options=options, challenge=challenge_b64)


@router.post("/passkey/register/verify", status_code=204)
async def passkey_register_verify(payload: PasskeyRegisterIn, user: CurrentUser, session: DB) -> None:
    """Verifica attestation e persiste a credencial."""
    info = wa.complete_registration(
        challenge_b64=payload.challenge,
        client_data_b64=payload.client_data_b64,
        attestation_b64=payload.attestation_b64,
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


@router.post("/passkey/login/options", response_model=PasskeyOptionsOut)
async def passkey_login_options(payload: PendingIn, session: DB) -> PasskeyOptionsOut:
    """Gera options para `navigator.credentials.get()`."""
    pending = await totp_mod.consume_pending(payload.pending_token)
    if pending is None:
        raise HTTPException(401, "pending invalid")
    keys = (
        await session.execute(
            text(
                "SELECT credential_id FROM user_passkeys WHERE user_id = :uid"
            ),
            {"uid": pending["user_id"]},
        )
        .mappings()
        .all()
    )
    if not keys:
        raise HTTPException(400, "no passkeys registered")
    options, challenge_b64 = wa.authentication_options([r["credential_id"] for r in keys])
    # Guarda challenge num pending atrelado ao mesmo user
    new_token = await totp_mod.store_pending(
        pending["user_id"], ip=pending.get("ip"), ua=pending.get("ua")
    )
    # Truque para devolver o novo pending_token junto: reusa o mesmo payload do pending.
    # Aqui simplificamos: cliente faz o GET e depois usa o token retornado no verify.
    return PasskeyOptionsOut(options=options, challenge=f"{challenge_b64}:{new_token}")


@router.post("/passkey/login/verify", response_model=None)
async def passkey_login_verify(payload: PasskeyLoginIn, request: Request, response: Response) -> dict:
    """Verifica assertion e emite cookie."""
    # payload.challenge contém "challenge_b64:pending_token"
    challenge_b64, pending_token = payload.challenge.split(":", 1)
    pending = await totp_mod.consume_pending(pending_token)
    if pending is None:
        raise HTTPException(401, "pending invalid")
    user_id = pending["user_id"]


    async with SessionLocal() as session:
        async with session.begin():
            pk = (
                await session.execute(
                    text(
                        "SELECT credential_id, public_key, sign_count "
                        "FROM user_passkeys WHERE user_id = :uid LIMIT 1"
                    ),
                    {"uid": user_id},
                )
                .mappings()
                .first()
            )
        if pk is None:
            raise HTTPException(401, "no passkey for user")

        new_sign_count = wa.complete_authentication(
            challenge_b64=challenge_b64,
            client_data_b64=payload.client_data_b64,
            authenticator_b64=payload.authenticator_b64,
            signature_b64=payload.signature_b64,
            sign_count=pk["sign_count"],
            pubkey_alg=-7,  # ES256 (default para passkeys modernos)
            pubkey=bytes(pk["public_key"]),
        )
        await session.execute(
            text(
                "UPDATE user_passkeys SET sign_count = :sc, last_used_at = now() "
                "WHERE user_id = :uid"
            ),
            {"sc": new_sign_count, "uid": user_id},
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
    return {"ok": True}


class PendingIn(BaseModel):
    pending_token: str


# Funções expostas para auth.login saber se o user tem 2FA habilitado
async def user_two_factor_methods(user_id: str, session: DB) -> list[str]:
    methods: list[str] = []
    row = (
        await session.execute(
            text("SELECT totp_enabled FROM users WHERE id = :uid"),
            {"uid": user_id},
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