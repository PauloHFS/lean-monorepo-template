"""WebAuthn (passkey) para 2FA sem senha de app.

Fluxo:
- registration_options()  — caller persiste o challenge no pending.
- complete_registration()  — caller persiste a credential no DB.
- authentication_options() — caller persiste o challenge no pending.
- complete_authentication() — caller atualiza sign_count.

Configuração: relying party = origin do front (settings.web_origin).
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url, options_to_json_dict
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings

_RP_NAME = "Lean Monorepo"


def rp_id_from_origin() -> str:
    """Extrai o host (sem porta, scheme) do web_origin."""
    parsed = urlparse(settings.web_origin)
    if parsed.hostname:
        return parsed.hostname
    # sem scheme — assume formato "host" ou "host:port"
    return settings.web_origin.split(":")[0]


# ---- Registration ---------------------------------------------------------
def registration_options(
    user_id: str, user_email: str, existing_keys: list[bytes]
) -> tuple[dict[str, Any], str]:
    """Gera opções para `navigator.credentials.create()`. Devolve (options_dict, challenge_b64)."""
    options = generate_registration_options(
        rp_id=rp_id_from_origin(),
        rp_name=_RP_NAME,
        user_id=uuid.UUID(user_id).bytes,
        user_name=user_email,
        user_display_name=user_email,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=k) for k in existing_keys] or None,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return options_to_json_dict(options), bytes_to_base64url(options.challenge)


def complete_registration(*, challenge_b64: str, credential: dict[str, Any]) -> dict[str, Any]:
    """Verifica attestation do cliente. Devolve dados para persistir."""
    result = verify_registration_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(challenge_b64),
        expected_rp_id=rp_id_from_origin(),
        expected_origin=settings.web_origin,
    )
    return {
        "credential_id": result.credential_id,
        "public_key": result.credential_public_key,
        "sign_count": result.sign_count,
    }


# ---- Authentication --------------------------------------------------------
def authentication_options(existing_keys: list[bytes]) -> tuple[dict[str, Any], str]:
    """Gera opções para `navigator.credentials.get()`. Devolve (options_dict, challenge_b64)."""
    options = generate_authentication_options(
        rp_id=rp_id_from_origin(),
        allow_credentials=[PublicKeyCredentialDescriptor(id=k) for k in existing_keys] or None,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return options_to_json_dict(options), bytes_to_base64url(options.challenge)


def complete_authentication(
    *,
    challenge_b64: str,
    credential: dict[str, Any],
    public_key: bytes,
    sign_count: int,
) -> int:
    """Verifica assertion. Devolve o novo sign_count (caller atualiza DB)."""
    result = verify_authentication_response(
        credential=credential,
        expected_challenge=base64url_to_bytes(challenge_b64),
        expected_rp_id=rp_id_from_origin(),
        expected_origin=settings.web_origin,
        credential_public_key=public_key,
        credential_current_sign_count=sign_count,
    )
    return result.new_sign_count
