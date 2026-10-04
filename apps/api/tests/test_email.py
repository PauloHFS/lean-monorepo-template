"""Tests do módulo email (sem rede)."""

from app.core.email import EmailMessage, SmtpProvider, get_provider


def setup_function(_):
    """Cada teste começa com cache limpo (EMAIL_LOG_ONLY ou envs não vazam)."""
    get_provider.cache_clear()


def teardown_function(_):
    get_provider.cache_clear()


def test_default_provider_is_smtp():
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p._host == "localhost"
    assert p._port == 1025


def test_smtp_provider_reads_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "resend")
    monkeypatch.setenv("SMTP_PASSWORD", "re_test_xxx")
    monkeypatch.setenv("SMTP_SSL", "true")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@test")
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p._host == "smtp.resend.com"
    assert p._port == 465
    assert p._username == "resend"
    assert p._password == "re_test_xxx"
    assert p._use_ssl is True
    assert p._starttls is False


def test_smtp_provider_starttls(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "email-smtp.us-east-1.amazonaws.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    p = get_provider()
    assert isinstance(p, SmtpProvider)
    assert p._starttls is True
    assert p._use_ssl is False


def test_log_only_flag(monkeypatch):
    monkeypatch.setenv("EMAIL_LOG_ONLY", "true")
    p = get_provider()
    assert p._log_only is True


def test_email_message_construction():
    m = EmailMessage(to="a@b.com", subject="hi", text="hello", html="<p>hello</p>")
    assert m.to == "a@b.com"
    assert m.subject == "hi"
    assert m.text == "hello"
    assert m.html == "<p>hello</p>"
    assert m.from_email is None


def test_email_message_accepts_list_of_recipients():
    m = EmailMessage(to=["a@b.com", "c@d.com"], subject="x")
    assert m.to == ["a@b.com", "c@d.com"]