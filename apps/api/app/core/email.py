"""Email transacional — SMTP-first.

Por que SMTP? Quase todo provedor (Resend, SES, Postmark, Mailgun, Brevo,
Mailjet, Zoho) tem SMTP. Um caminho de código, N provedores. A unica coisa
que muda sao 4 vars de conexao:
    SMTP_HOST=mailpit                       # dev
    SMTP_PORT=1025                         # 1025 (Mailpit), 587 (STARTTLS), 465 (TLS)
    SMTP_USER=...                          # opcional, se provedor exige auth
    SMTP_PASSWORD=...                      # opcional
    SMTP_SSL=true                          # port 465 (TLS implicito); false pra STARTTLS
    SMTP_STARTTLS=false                    # port 587 (upgrade); true se provedor exige

Pluggable mesmo assim — LoggingProvider so loga (CI/tests, sem SMTP).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from email.message import EmailMessage as PyEmailMessage
from functools import lru_cache
from typing import Protocol

import aiosmtplib

from app.core.logging import get_logger


@dataclass(slots=True)
class EmailMessage:
    to: str | list[str]
    subject: str
    text: str | None = None  # fallback plain
    html: str | None = None
    from_email: str | None = None  # override do EMAIL_FROM


class EmailProvider(Protocol):
    async def send(self, msg: EmailMessage) -> None: ...


class LoggingProvider:
    """So loga o payload (CI/tests)."""

    def __init__(self) -> None:
        self._log = get_logger("email")

    async def send(self, msg: EmailMessage) -> None:
        recipients = msg.to if isinstance(msg.to, list) else [msg.to]
        self._log.info(
            "email (stub)",
            to=recipients,
            subject=msg.subject,
            text_len=len(msg.text or ""),
            html_len=len(msg.html or ""),
        )


class SmtpProvider:
    """SMTP generico. Dev: Mailpit. Prod: Resend/SES/Postmark/etc."""

    def __init__(
        self,
        host: str,
        port: int,
        from_email: str,
        *,
        user: str | None = None,
        password: str | None = None,
        ssl: bool = False,      # TLS implicito (port 465)
        starttls: bool = False,  # STARTTLS (port 587)
    ) -> None:
        self._host = host
        self._port = port
        self._from = from_email
        self._user = user
        self._password = password
        self._ssl = ssl
        self._starttls = starttls
        self._log = get_logger("email.smtp")

    async def send(self, msg: EmailMessage) -> None:
        recipients = msg.to if isinstance(msg.to, list) else [msg.to]

        # Constrói mensagem MIME padrão do Python (multipart text/html)
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
            use_tls=self._ssl,
        ) as client:
            if self._user and self._password:
                await client.login(self._user, self._password)
            if self._starttls and not self._ssl:
                await client.starttls()
            await client.send_message(py_msg)

        self._log.info(
            "email enviado via SMTP",
            to=recipients,
            subject=msg.subject,
            host=self._host,
            port=self._port,
        )


@lru_cache(maxsize=1)
def get_provider() -> EmailProvider:
    """Factory. EMAIL_PROVIDER=logging pra modo stub. Qualquer outro s: SMTP."""
    kind = os.environ.get("EMAIL_PROVIDER", "smtp").lower()
    from_email = os.environ.get("EMAIL_FROM", "noreply@example.com")

    if kind == "logging":
        return LoggingProvider()

    # SMTP (default e qualquer valor nao-reconhecido cai aqui)
    return SmtpProvider(
        host=os.environ.get("SMTP_HOST", "localhost"),
        port=int(os.environ.get("SMTP_PORT", "1025")),
        from_email=from_email,
        user=os.environ.get("SMTP_USER") or None,
        password=os.environ.get("SMTP_PASSWORD") or None,
        ssl=os.environ.get("SMTP_SSL", "false").lower() == "true",
        starttls=os.environ.get("SMTP_STARTTLS", "false").lower() == "true",
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