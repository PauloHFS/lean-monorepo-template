"""Contract tests: rotas devem expor response models utilizáveis no TS gerado.

O FastAPI gera o OpenAPI a partir do `response_model` de cada rota; validar o
`$ref` do 200 é a forma mais simples (e estável) de provar o contrato.
"""

from __future__ import annotations

from typing import Any

from app.main import app


def _openapi_response_schema(path: str) -> dict[str, Any]:
    schema: dict[str, Any] = app.openapi()
    response: dict[str, Any] = schema["paths"][path]["post"]["responses"]["200"]
    content: dict[str, Any] = response["content"]["application/json"]
    return content["schema"]


def _openapi_schemas() -> dict[str, Any]:
    schemas: dict[str, Any] = app.openapi()["components"]["schemas"]
    return schemas


def test_login_declares_login_out_response_model() -> None:
    assert _openapi_response_schema("/api/v1/auth/login")["$ref"] == (
        "#/components/schemas/LoginOut"
    )


def test_verify_routes_declare_ok_out_response_model() -> None:
    for path in ("/api/v1/auth/2fa/verify", "/api/v1/auth/2fa/passkey/login/verify"):
        assert _openapi_response_schema(path)["$ref"] == "#/components/schemas/OkOut"


def test_openapi_login_200_has_usable_properties() -> None:
    properties = _openapi_schemas()["LoginOut"]["properties"]
    assert set(properties) == {"requires_2fa", "pending_token", "methods", "user"}


def test_openapi_ok_out_has_bool_property() -> None:
    ok_out = _openapi_schemas()["OkOut"]
    assert ok_out["properties"] == {"ok": {"title": "Ok", "type": "boolean"}}


def test_openapi_delete_user_path_param_is_uuid() -> None:
    param = app.openapi()["paths"]["/api/v1/users/{user_id}"]["delete"]["parameters"][0]
    assert param["in"] == "path"
    assert param["schema"]["format"] == "uuid"
