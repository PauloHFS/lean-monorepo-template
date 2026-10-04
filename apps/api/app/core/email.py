"""Email transacional — SMTP-only.

Quase todo provedor moderno aceita SMTP:
- Resend: smtp.resend.com:465 (user=`resend`, senha=API key)
- AWS SES: email-smtp.<region>.amazonaws.com:587 (STARTTLS + IAM user)
- Postmark: smtp.postmarkapp.com:587 (STARTTLS)
- Mailgun: smtp.mailgun.org:587 (STARTTLS)
- Brevo: smtp-relay.brevo.com:587 (STARTTLS)
- Dev local: Mailpit no compose (porta 1025, sem TLS)

Configuração:
    SMTP_HOST=mailpit                  # dev
    SMTP_PORT=1025
    SMTP_USERNAME=                     # vazio = sem auth (Mailpit)
    SMTP_PASSWORD=
    SMTP_SSL=false                     # true p/ porta 465
    SMTP_STARTTLS=false                # true p/ porta 587
    EMAIL_FROM="App <noreply@example.com>"
    EMAIL_LOG_ONLY=false               # true = não envia, só loga

Por que SMTP-only? Um único código, um único caminho de erro, todos os provedores.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from email.message import EmailMessage as PyEmailMessage
from functools import lru_cache

import aiosmtplib

from app.core.logging import get_logger


@dataclass(slots=True)
class EmailMessage:
    to: str | list[str]
    subject: str
    text: str | None = None  # fallback plain
    html: str | None = None
    from_email: str | None = None  # override do EMAIL_FROM


class SmtpProvider:
    """SMTP universal. Dev → Mailpit (porta 1025, sem TLS).
    Prod → qualquer provedor via variáveis de ambiente."""

    def __init__(
        self,
        host: str,
        port: int,
        from_email: str,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        starttls: bool = False,
        log_only: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._from = from_email
        self._username = username or None
        self._password = password or None
        self._use_ssl = use_ssl
        self._starttls = starttls
        self._log_only = log_only
        self._log = get_logger("email")

    async def send(self, msg: EmailMessage) -> None:
        recipients = msg.to if isinstance(msg.to, list) else [msg.to]

        if self._log_only:
            self._log.info(
                "email (log-only)",
                to=recipients,
                subject=msg.subject,
                host=self._host,
                text_len=len(msg.text or ""),
                html_len=len(msg.html or ""),
            )
            return

        # Constrói mensagem MIME padrão do Python (multipart/alternative se text+html).
        py_msg = PyEmailMessage()
        py_msg["From"] = msg.from_email or self._from
        py_msg["To"] = ", ".join(recipients)
        py_msg["Subject"] = msg.subject
        if msg.text:
            py_msg.set_content(msg.text)
        if msg.html:
            py_msg.add_alternative(msg.html, subtype="html")

        async with aiosmtplib.SMTP(
            hostname=self._host,
            port=self._port,
            use_tls=self._use_ssl,
        ) as client:
            if self._starttls and not self._use_ssl:
                await client.starttls()
            if self._username and self._password:
                await client.login(self._username, self._password)
            await client.send_message(py_msg)

        self._log.info(
            "email enviado",
            to=recipients,
            subject=msg.subject,
            host=self._host,
        )


@lru_cache(maxsize=1)
def get_provider() -> SmtpProvider:
    """SMTP é default. Qualquer coisa SMTP-relay (Mailpit, Resend, SES, ...) funciona."""
    return SmtpProvider(
        host=os.environ.get("SMTP_HOST", "localhost"),
        port=int(os.environ.get("SMTP_PORT", "1025")),
        from_email=os.environ.get("EMAIL_FROM", "noreply@example.com"),
        username=os.environ.get("SMTP_USERNAME"),
        password=os.environ.get("SMTP_PASSWORD"),
        use_ssl=os.environ.get("SMTP_SSL", "false").lower() == "true",
        starttls=os.environ.get("SMTP_STARTTLS", "false").lower() == "true",
        log_only=os.environ.get("EMAIL_LOG_ONLY", "false").lower() == "true",
    )


async def send_email(
    to: str | list[str],
    subject: str,
    *,
    text: str | None = None,
    html: str | None = None,
) -> None:
    """Atalho: pega provider + chama send."""
    await get_provider().send(
        EmailMessage(to=to, subject=subject, text=text, html=html)
    )