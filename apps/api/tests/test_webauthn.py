"""Tests do WebAuthn (helpers puros: rp_id extraction, opções e challenge)."""

import base64
import uuid

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.api.v1.endpoints import twofa
from app.core import webauthn as wa


def _decode_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _assert_b64url_no_padding(value: str) -> None:
    assert value
    assert "=" not in value
    assert "+" not in value
    assert "/" not in value
    assert _decode_b64url(value)


def test_rp_id_from_origin_strips_http_scheme(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "http://localhost:5173")
    assert wa.rp_id_from_origin() == "localhost"


def test_rp_id_from_origin_strips_https_and_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "https://app.example.com:8443")
    assert wa.rp_id_from_origin() == "app.example.com"


def test_rp_id_from_origin_handles_no_scheme(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "localhost:5173")
    assert wa.rp_id_from_origin() == "localhost"


def test_registration_options_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "https://app.example.com")
    user_id = str(uuid.uuid4())
    key = b"\x01\x02\x03"

    options, challenge = wa.registration_options(
        user_id=user_id, user_email="user@example.com", existing_keys=[key]
    )

    _assert_b64url_no_padding(challenge)
    assert options["rp"]["id"] == "app.example.com"
    assert options["user"]["name"] == "user@example.com"
    assert options["user"]["id"] == wa.bytes_to_base64url(uuid.UUID(user_id).bytes)
    assert options["challenge"] == challenge
    assert options["excludeCredentials"] == [
        {"id": wa.bytes_to_base64url(key), "type": "public-key"}
    ]


def test_registration_options_without_existing_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "http://localhost:5173")
    options, challenge = wa.registration_options(
        user_id=str(uuid.uuid4()), user_email="user@example.com", existing_keys=[]
    )
    _assert_b64url_no_padding(challenge)
    assert options["excludeCredentials"] == []


def test_authentication_options_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "https://app.example.com")
    keys = [b"\x0a\x0b", b"\x0c\x0d"]

    options, challenge = wa.authentication_options(keys)

    _assert_b64url_no_padding(challenge)
    assert options["rpId"] == "app.example.com"
    assert options["challenge"] == challenge
    assert options["allowCredentials"] == [
        {"id": wa.bytes_to_base64url(k), "type": "public-key"} for k in keys
    ]


@hypothesis_settings(deadline=None, max_examples=20)
@given(st.uuids())
def test_generated_challenge_is_base64url_without_padding(user_id: uuid.UUID):
    _options, challenge = wa.registration_options(
        user_id=str(user_id), user_email="user@example.com", existing_keys=[]
    )
    _assert_b64url_no_padding(challenge)


# ---- Contrato Pydantic (OpenAPI/TS) -----------------------------------------
def test_registration_options_round_trip_keeps_every_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "https://app.example.com")
    options, _challenge = wa.registration_options(
        user_id=str(uuid.uuid4()),
        user_email="user@example.com",
        existing_keys=[b"\x01\x02\x03"],
    )
    model = twofa.PasskeyRegistrationOptionsOut.model_validate(options)
    assert model.model_dump() == options


def test_authentication_options_round_trip_keeps_every_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wa.settings, "web_origin", "https://app.example.com")
    options, _challenge = wa.authentication_options([b"\x0a\x0b", b"\x0c\x0d"])
    model = twofa.PasskeyAuthenticationOptionsOut.model_validate(options)
    assert model.model_dump() == options


def _registration_credential(**overrides: object) -> dict[str, object]:
    credential: dict[str, object] = {
        "id": "AQID",
        "rawId": "AQID",
        "type": "public-key",
        "response": {"clientDataJSON": "abc", "attestationObject": "def"},
    }
    credential.update(overrides)
    return credential


def test_registration_credential_accepts_missing_transports():
    cred = twofa.PasskeyRegistrationCredential.model_validate(_registration_credential())
    assert cred.response.transports is None
    assert cred.response.attestationObject == "def"


def test_registration_credential_rejects_unknown_type():
    with pytest.raises(ValidationError):
        twofa.PasskeyRegistrationCredential.model_validate(
            _registration_credential(type="not-a-key")
        )


def test_registration_credential_requires_client_data_json():
    credential = _registration_credential()
    credential["response"] = {"attestationObject": "def"}
    with pytest.raises(ValidationError):
        twofa.PasskeyRegistrationCredential.model_validate(credential)


def test_authentication_credential_accepts_optional_user_handle():
    cred = twofa.PasskeyAuthenticationCredential.model_validate(
        {
            "id": "AQID",
            "rawId": "AQID",
            "type": "public-key",
            "response": {
                "clientDataJSON": "abc",
                "authenticatorData": "def",
                "signature": "ghi",
            },
        }
    )
    assert cred.response.userHandle is None
