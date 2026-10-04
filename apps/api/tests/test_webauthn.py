"""Tests do WebAuthn (helpers puros: rp_id extraction, validação de inputs)."""
from app.core import webauthn as wa


def test_rp_id_from_origin_strips_http_scheme():
    # com http:// ; set http
    wa.settings.web_origin = "http://localhost:5173"
    assert wa.rp_id_from_origin() == "localhost"


def test_rp_id_from_origin_strips_https_and_port():
    wa.settings.web_origin = "https://app.example.com:8443"
    assert wa.rp_id_from_origin() == "app.example.com"


def test_rp_id_from_origin_handles_no_scheme():
    wa.settings.web_origin = "localhost:5173"
    assert wa.rp_id_from_origin() == "localhost"


def test_rp_factory_uses_settings():
    wa.settings.web_origin = "https://app.example.com"
    rp = wa._rp()
    assert rp.id == "app.example.com"
    assert rp.name == "Lean Monorepo"