"""Tests do runner — funções puras, sem DB."""
from datetime import timedelta

from app.jobs.runner import build_claim_sql, compute_backoff


def test_build_claim_sql_has_skip_locked_and_ordering():
    sql, params = build_claim_sql(batch_size=5, queues=None)
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "ORDER BY run_at" in sql
    assert "LIMIT :batch" in sql
    assert "RETURNING" in sql
    assert params["batch"] == 5
    assert "worker" in params
    # Não filtra por queue quando None
    assert "ANY(:queues)" not in sql


def test_build_claim_sql_filters_by_queue_when_provided():
    sql, params = build_claim_sql(batch_size=10, queues=["default", "priority"])
    assert "AND queue = ANY(:queues)" in sql
    assert params["queues"] == ["default", "priority"]
    assert params["batch"] == 10


def test_build_claim_sql_handles_all_queues_passed_through():
    """Garante que a lista de filas é passada como parâmetro, não interpolada."""
    sql, _ = build_claim_sql(batch_size=1, queues=["evil'; DROP TABLE users;--"])
    # O nome da fila malicioso não aparece inline no SQL
    assert "evil" not in sql


def test_compute_backoff_is_exponential_capped():
    assert compute_backoff(0) == timedelta(seconds=1)
    assert compute_backoff(1) == timedelta(seconds=2)
    assert compute_backoff(2) == timedelta(seconds=4)
    assert compute_backoff(3) == timedelta(seconds=8)
    assert compute_backoff(10) == timedelta(seconds=300)  # cap
    assert compute_backoff(50) == timedelta(seconds=300)  # cap