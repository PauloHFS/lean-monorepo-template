"""Tests das tasks de jobs (Procrastinate)."""
from __future__ import annotations

import procrastinate
from procrastinate import testing

from app.jobs.app import app
from app.jobs.tasks.email import send_email


def test_app_is_procrastinate_app() -> None:
    assert isinstance(app, procrastinate.App)


def test_send_email_is_registered_task() -> None:
    assert send_email.name == "email.send"
    assert send_email.queue == "email"
    assert callable(send_email.defer)
    assert callable(send_email.defer_async)


async def test_send_email_defer_enqueues_job() -> None:
    connector = testing.InMemoryConnector()
    with app.replace_connector(connector) as test_app:
        async with test_app.open_async():
            job_id = await send_email.defer_async(to="x@y.com", subject="hi")

    assert job_id is not None
    assert len(connector.jobs) == 1
    job = next(iter(connector.jobs.values()))
    assert job["task_name"] == "email.send"
    assert job["queue_name"] == "email"
    assert job["args"] == {"to": "x@y.com", "subject": "hi"}
