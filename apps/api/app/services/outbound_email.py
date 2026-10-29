"""Serviço de disparo de e-mail (job `email.send` no Procrastinate)."""

from __future__ import annotations

from opentelemetry import trace

from app.core.observability import inject_trace_context
from app.jobs.app import defer_job
from app.jobs.tasks.email import send_email
from app.permissions import Action, Actor, Resource, authorize


async def enqueue_email(actor: Actor, *, to: str, subject: str, body: str) -> int:
    """Autoriza (`create email`) e enfileira; devolve o id do job."""
    authorize(actor, Action.CREATE, Resource.EMAIL)
    tracer = trace.get_tracer("lean.api")
    with tracer.start_as_current_span("email.enqueue"):
        job_payload = inject_trace_context({"to": to, "subject": subject, "text": body})
        return await defer_job(
            send_email,
            rate_limit_kind="email.send",
            rate_limit_key=f"user:{actor.id}",
            rate_limit_limit=20,
            rate_limit_window_s=60,
            **job_payload,
        )
