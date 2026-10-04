"""Tests do módulo email (sem rede)."""

import pytest

from app.core.email import EmailMessage, LoggingProvider, SmtpProvider, get_provider


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()


def test_default_provider_is_smtp(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p._host == "localhost"
    assert p._port == 1025


def test_logging_provider_when_explicit(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "logging")
    p = get_provider()
    assert isinstance(p, LoggingProvider)


def test_smtp_provider_reads_env(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "resend")
    monkeypatch.setenv("SMTP_PASSWORD", "re_test_xxx")
    monkeypatch.setenv("SMTP_SSL", "true")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@test")
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p._host == "smtp.resend.com"
    assert p._port == 465
    assert p._user == "resend"
    assert p._password == "re_test_xxx"
    assert p._ssl is True
    assert p._starttls is False


def test_smtp_provider_starttls(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "email-smtp.us-east-1.amazonaws.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p._starttls is True
    assert p._ssl is False


def test_unknown_provider_kind_falls_back_to_smtp(monkeypatch):
    """Qualquer valor desconhecido cai no SMTP (não falha)."""
    monkeypatch.setenv("EMAIL_PROVIDER", "garbage")
    p = get_provider()
    assert isinstance(p, SmtpProvider)


def test_email_message_construction():
    m = EmailMessage(to="a@b.com", subject="hi", text="hello", html="<p>hello</p>")
    assert m.to == "a@b.com"
    assert m.subject == "hi"
    assert m.text == "hello"
    assert m.html == "<p>hello</p>"
    assert m.from_email is None  # default


def test_email_message_accepts_list_of_recipients():
    m = EmailMessage(to=["a@b.com", "c@d.com"], subject="x")
    assert m.to == ["a@b.com", "c@d.com"]