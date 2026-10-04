"""WebAuthn (passkey) para 2FA sem senha de app.

Fluxo:
- registration_options_for() + persistir challenge no cache.
- verify_registration()    — caller persiste credential no DB.
- authentication_options_for() + persistir challenge no cache.
- verify_authentication()  — caller atualiza sign_count.

Configuração: relying party = origin do front (settings.web_origin).
"""
from __future__ import annotations

from typing import Any

from webauthn import (
    create_webauthn_credentials,
    get_webauthn_credentials,
    verify_create_webauthn_credentials,
    verify_get_webauthn_credentials,
)
from webauthn.metadata import FIDOMetadata
from webauthn.types import RelyingParty, User, UserVerification

from app.core.config import settings

_RP_NAME = "Lean Monorepo"
_USER_VERIFICATION = UserVerification.Preferred


def rp_id_from_origin() -> str:
    """Extrai o host (sem porta, scheme) do web_origin."""
    origin = settings.web_origin
    for prefix in ("http://", "https://"):
        if origin.startswith(prefix):
            return origin[len(prefix) :].split(":")[0]
    # sem scheme — assume formato "host" ou "host:port"
    return origin.split(":")[0]


def _rp() -> RelyingParty:
    return RelyingParty(id=rp_id_from_origin(), name=_RP_NAME, icon=None)


def _user(user_id: str, email: str) -> User:
    return User(id=user_id.encode("utf-8"), name=email, display_name=email)


# ---- Registration ---------------------------------------------------------
def registration_options(user_id: str, user_email: str, existing_keys: list[bytes]) -> tuple[dict, str]:
    """Gera opções para `navigator.credentials.create()`. Devolve (options_dict, challenge_b64)."""
    options, challenge_b64 = create_webauthn_credentials(
        rp=_rp(),
        user=_user(user_id, user_email),
        existing_keys=existing_keys,
        user_verification=_USER_VERIFICATION,
    )
    return options, challenge_b64


def complete_registration(
    *,
    challenge_b64: str,
    client_data_b64: str,
    attestation_b64: str,
) -> dict[str, Any]:
    """Verifica attestation do cliente. Devolve dados para persistir."""
    result = verify_create_webauthn_credentials(
        rp=_rp(),
        challenge_b64=challenge_b64,
        client_data_b64=client_data_b64,
        attestation_b64=attestation_b64,
        fido_metadata=FIDOMetadata(),
        user_verification_required=False,
    )
    return {
        "credential_id": result.credential_id,
        "public_key": result.public_key,
        "sign_count": result.sign_count,
    }


# ---- Authentication --------------------------------------------------------
def authentication_options(existing_keys: list[bytes]) -> tuple[dict, str]:
    """Gera opções para `navigator.credentials.get()`. Devolve (options_dict, challenge_b64)."""
    options, challenge_b64 = get_webauthn_credentials(
        rp=_rp(),
        existing_keys=existing_keys,
        user_verification=_USER_VERIFICATION,
    )
    return options, challenge_b64


def complete_authentication(
    *,
    challenge_b64: str,
    client_data_b64: str,
    authenticator_b64: str,
    signature_b64: str,
    sign_count: int,
    pubkey_alg: int,
    pubkey: bytes,
) -> int:
    """Verifica assertion. Devolve o novo sign_count (caller atualiza DB)."""
    result = verify_get_webauthn_credentials(
        rp=_rp(),
        challenge_b64=challenge_b64,
        client_data_b64=client_data_b64,
        authenticator_b64=authenticator_b64,
        signature_b64=signature_b64,
        sign_count=sign_count,
        pubkey_alg=pubkey_alg,
        pubkey=pubkey,
        user_verification_required=False,
    )
    return result.new_sign_count