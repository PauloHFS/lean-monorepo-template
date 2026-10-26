"""Task: envio de e-mail via SMTP.

SMTP universal: configurar SMTP_HOST/PORT/USERNAME/PASSWORD (e SMTP_SSL ou SMTP_STARTTLS).
Em dev → Mailpit (captura na UI localhost:8025). Em prod → Resend/SES/Postmark/Mailgun/Brevo.
EMAIL_LOG_ONLY=true pra desativar envio e só logar.

Procrastinate: a task recebe o `JobContext` como primeiro argumento
(`pass_context=True`); os demais args são keyword-only no defer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import procrastinate
from opentelemetry import trace
from opentelemetry.context import Context

from app.core import email as email_module
from app.core.observability import extract_trace_context
from app.jobs.app import app


@app.task(queue="email", name="email.send", retry=True, pass_context=True)
async def send_email(
    ctx: procrastinate.JobContext,
    to: str | list[str],
    subject: str,
    text: str | None = None,
    html: str | None = None,
    trace_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Envia e-mail. Retorna {"to": [...], "subject": "..."} como resultado do job.

    `ctx` fica disponível para middlewares/logs futuros; o corpo não o usa ainda.
    Quando o payload traz `trace_context`, o span `email.send` é filho do span
    que enfileirou o job; enfileiramentos manuais/CLI sem contexto rodam como
    span raiz.
    """
    parent: Context = (
        extract_trace_context({"trace_context": trace_context}) if trace_context else Context()
    )
    tracer = trace.get_tracer("lean.worker")
    with tracer.start_as_current_span("email.send", context=parent):
        recipients = to if isinstance(to, list) else [to]
        await email_module.send_email(to=to, subject=subject, text=text, html=html)
        return {"to": recipients, "subject": subject}
