"""Enqueue-email: devolve o job id do Procrastinate (defer mockado)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.api.v1.endpoints.users import EnqueueEmailIn, enqueue_email
from app.jobs.tasks.email import send_email


async def test_enqueue_email_returns_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _defer(**_kwargs: Any) -> int:
        return 42

    monkeypatch.setattr(send_email, "defer_async", _defer)
    payload = EnqueueEmailIn(to="a@b.com", subject="hi", body="hello")
    user = SimpleNamespace(id=uuid4())

    out = await enqueue_email(payload, user=user)  # type: ignore[arg-type]

    assert out.job_id == 42
    assert out.status == "queued"
