"""Enqueue-email: devolve o job id do Procrastinate (defer mockado)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.api.v1.endpoints.users import EnqueueEmailIn, enqueue_email
from app.jobs.tasks.email import send_email
from app.permissions import Actor, Role


async def test_enqueue_email_returns_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _defer(**_kwargs: Any) -> int:
        return 42

    async def _no_rate_limit(*_args: Any, **_kwargs: Any) -> int:
        return 1

    monkeypatch.setattr("app.jobs.app.check_job_rate_limit", _no_rate_limit)
    monkeypatch.setattr(send_email, "defer_async", _defer)
    payload = EnqueueEmailIn(to="a@b.com", subject="hi", body="hello")
    actor = Actor(id=uuid4(), role=Role.ADMIN)

    out = await enqueue_email(payload, actor=actor)

    assert out.job_id == 42
    assert out.status == "queued"
