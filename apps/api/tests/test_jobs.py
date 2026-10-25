"""Tests das tasks de jobs (Procrastinate) e do job de exemplo legado."""

from __future__ import annotations

import json

import procrastinate
import pytest
from procrastinate import testing
from pydantic import ValidationError

from app import cli
from app.api.v1.endpoints.users import EnqueueEmailOut
from app.cli import EXAMPLE_JOB_SQL, example_job_payload
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


def test_enqueue_email_out_job_id_is_int() -> None:
    out = EnqueueEmailOut(job_id=42, status="queued")
    assert out.job_id == 42
    with pytest.raises(ValidationError):
        EnqueueEmailOut(job_id="not-an-int", status="queued")  # type: ignore[arg-type]


def test_example_job_payload_has_expected_keys_and_is_json_serializable() -> None:
    payload = example_job_payload()
    assert set(payload) == {"to", "subject", "text"}
    assert json.loads(json.dumps(payload)) == payload


def test_example_job_payload_is_a_fresh_copy() -> None:
    first = example_job_payload()
    first["to"] = "mutated@example.com"
    assert example_job_payload()["to"] == "someone@example.com"


def test_example_job_command_is_registered() -> None:
    registry: dict[str, object] = vars(cli)["_REGISTRY"]
    assert "example-job" in registry


def test_example_job_sql_is_literal_and_uses_bind_params() -> None:
    """Valores (inclusive o payload) vão por bind param, nunca interpolados."""
    assert "INSERT INTO background_jobs" in EXAMPLE_JOB_SQL
    for param in (":queue", ":kind", ":payload", ":status", ":max_attempts"):
        assert param in EXAMPLE_JOB_SQL
    assert "CAST(:payload AS jsonb)" in EXAMPLE_JOB_SQL
    # Nenhum valor concreto / f-string vazou para o SQL.
    assert "example.task" not in EXAMPLE_JOB_SQL
    assert "someone@example.com" not in EXAMPLE_JOB_SQL
    assert "{" not in EXAMPLE_JOB_SQL
