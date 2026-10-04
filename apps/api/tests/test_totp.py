"""Tests do TOTP (sem DB: puro)."""
import time

import pyotp

from app.core import totp as totp_mod


def test_generate_secret_has_correct_length():
    secret = totp_mod.generate_secret()
    # pyotp default: 32 chars base32 de 20 bytes
    assert len(secret) == 32
    # base32 é uppercase A-Z 2-7
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)


def test_encrypt_decrypt_roundtrip():
    secret = totp_mod.generate_secret()
    encrypted = totp_mod.encrypt_secret(secret)
    # encrypted é bytes e diferente do original
    assert isinstance(encrypted, bytes)
    assert encrypted != secret.encode()
    # roundtrip
    assert totp_mod.decrypt_secret(encrypted) == secret


def test_provisioning_uri_is_otpauth():
    uri = totp_mod.provisioning_uri("SECRET", "user@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "user%40example.com" in uri or "user@example.com" in uri
    assert "Lean%20Monorepo" in uri or "Lean+Monorepo" in uri or "Lean Monorepo" in uri


def test_verify_totp_accepts_current_code():
    secret = totp_mod.generate_secret()
    code = pyotp.TOTP(secret).now()
    assert totp_mod.verify_totp(secret, code) is True


def test_verify_totp_rejects_wrong_code():
    secret = totp_mod.generate_secret()
    # código claramente errado
    assert totp_mod.verify_totp(secret, "000000") is False


def test_verify_totp_rejects_old_code_outside_window():
    secret = totp_mod.generate_secret()
    # Gera código de 2 minutos atrás (fora da janela ±1 step)
    old_code = pyotp.TOTP(secret).at(time.time() - 120)
    assert totp_mod.verify_totp(secret, old_code, valid_window=0) is False


def test_recovery_codes_count_and_alphabet():
    codes = totp_mod.generate_recovery_codes(n=10)
    assert len(codes) == 10
    # alfabeto: a-z + 0-9
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789")
    for c in codes:
        assert len(c) == 10
        assert all(ch in allowed for ch in c)


def test_recovery_codes_are_unique():
    codes = totp_mod.generate_recovery_codes(n=100)
    assert len(set(codes)) == 100


def test_hash_recovery_code_is_deterministic_and_safe():
    h1 = totp_mod.hash_recovery_code("abc123")
    h2 = totp_mod.hash_recovery_code("abc123")
    assert h1 == h2
    assert len(h1) == 64
    assert h1 != "abc123"  # não é plain text