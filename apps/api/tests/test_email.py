"""Tests do módulo email (sem rede)."""

import pytest

from app.core.email import EmailMessage, SmtpProvider, get_provider


def setup_function(_) -> None:
    """Cada teste começa com cache limpo (EMAIL_LOG_ONLY ou envs não vazam)."""
    get_provider.cache_clear()


def teardown_function(_) -> None:
    get_provider.cache_clear()


def test_default_provider_is_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    # O .env de dev pode setar SMTP_HOST/SMTP_PORT; o default do provider é fixo.
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p.host == "localhost"
    assert p.port == 1025


def test_smtp_provider_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "resend")
    monkeypatch.setenv("SMTP_PASSWORD", "re_test_xxx")
    monkeypatch.setenv("SMTP_SSL", "true")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@test")
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p.host == "smtp.resend.com"
    assert p.port == 465
    assert p.username == "resend"
    assert p.password == "re_test_xxx"
    assert p.use_ssl is True
    assert p.starttls is False


def test_smtp_provider_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "email-smtp.us-east-1.amazonaws.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p.starttls is True
    assert p.use_ssl is False


def test_log_only_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_LOG_ONLY", "true")
    p = get_provider()
    assert p.log_only is True


def test_email_message_construction() -> None:
    m = EmailMessage(to="a@b.com", subject="hi", text="hello", html="<p>hello</p>")
    assert m.to == "a@b.com"
    assert m.subject == "hi"
    assert m.text == "hello"
    assert m.html == "<p>hello</p>"
    assert m.from_email is None


def test_email_message_accepts_list_of_recipients() -> None:
    m = EmailMessage(to=["a@b.com", "c@d.com"], subject="x")
    assert m.to == ["a@b.com", "c@d.com"]
