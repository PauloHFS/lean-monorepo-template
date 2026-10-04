"""Task: envio de e-mail via provider SMTP.

SMTP-first: configurar SMTP_HOST/PORT/USER/PASSWORD. Em dev → Mailpit
(captura na UI localhost:8025). Em prod → Resend, SES, Postmark, etc.
EMAIL_PROVIDER=logging pra desativar SMTP e só logar.
"""
from __future__ import annotations

from app.core import email
from app.jobs.tasks.registry import JobContext


async def send_email(ctx: JobContext) -> None:
    to = ctx.payload.get("to")
    subject = ctx.payload.get("subject", "(sem assunto)")
    body = ctx.payload.get("body", "")
    html = ctx.payload.get("html")

    if not to:
        raise ValueError("payload.to é obrigatório")

    await email.send_email(
        to=to,
        subject=subject,
        text=body or None,
        html=html,
    )
    ctx.log.info("email task done", to=to, subject=subject)