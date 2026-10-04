"""Runner de background jobs baseado em Postgres SKIP LOCKED.

Por que não Redis/Celery/RQ? Menos infra, menos ops, transacional com o app.

Conceitos:
- claim: SELECT FOR UPDATE SKIP LOCKED + UPDATE na mesma transação.
- recover_stuck: libera jobs cujo worker morreu (locked_at < now - timeout).
- retries: ao falhar, attempts++. Quando attempts >= max_attempts → failed.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.jobs.tasks.registry import JobContext, get_task, known_kinds

log = get_logger("jobs.runner")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

_MAX_BACKOFF_S = 300  # 5 min


# =============================================================================
# Pure helpers (testáveis sem DB)
# =============================================================================
def build_claim_sql(batch_size: int, queues: list[str] | None) -> tuple[str, dict[str, Any]]:
    """Monta o CTE + UPDATE do claim. Retorna (sql, params)."""
    params: dict[str, Any] = {"batch": batch_size, "worker": WORKER_ID}
    queue_clause = ""
    if queues:
        queue_clause = "AND queue = ANY(:queues)"
        params["queues"] = queues

    sql = f"""
        WITH cte AS (
            SELECT id
              FROM background_jobs
             WHERE status IN ('pending', 'failed')
               AND attempts < max_attempts
               AND run_at <= :now
               {queue_clause}
             ORDER BY run_at
             LIMIT :batch
             FOR UPDATE SKIP LOCKED
        )
        UPDATE background_jobs j
           SET status      = 'running',
               locked_at   = :now,
               locked_by   = :worker,
               started_at  = COALESCE(j.started_at, :now),
               attempts    = j.attempts + 1,
               updated_at  = :now
          FROM cte
         WHERE j.id = cte.id
        RETURNING j.id, j.kind, j.payload, j.queue, j.attempts, j.max_attempts
    """
    return sql, params


def compute_backoff(attempts: int) -> timedelta:
    """Backoff exponencial capado em 5 min."""
    return timedelta(seconds=min(_MAX_BACKOFF_S, 2 ** attempts))


# =============================================================================
# Recover
# =============================================================================
RECOVER_SQL = """
    UPDATE background_jobs
       SET status     = 'pending',
           locked_at  = NULL,
           locked_by  = NULL,
           last_error = COALESCE(last_error || E'\\n', '')
                        || 'recovered: worker timeout'
     WHERE status = 'running'
       AND locked_at < :threshold
"""


async def recover_stuck() -> int:
    """Libera jobs travados por workers mortos. Chamado no startup."""
    threshold = datetime.now(UTC) - timedelta(
        seconds=settings.worker_visibility_timeout_s
    )
    async with SessionLocal() as session:
        result = await session.execute(text(RECOVER_SQL), {"threshold": threshold})
        await session.commit()
        n = result.rowcount or 0
        if n:
            log.warning("jobs recuperados após timeout", recovered=n)
        return n


# =============================================================================
# Claim
# =============================================================================
async def claim_batch(batch_size: int, queues: list[str] | None = None) -> list[dict[str, Any]]:
    """Reserva até `batch_size` jobs via CTE + FOR UPDATE SKIP LOCKED."""
    sql, params = build_claim_sql(batch_size, queues)
    params["now"] = datetime.now(UTC)

    async with SessionLocal() as session, session.begin():
        rows = (await session.execute(text(sql), params)).mappings().all()
        return [dict(r) for r in rows]


# =============================================================================
# Mark done / failed
# =============================================================================
async def _mark_done(job_id: Any) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE background_jobs
                   SET status = 'done',
                       finished_at = :now,
                       locked_at = NULL,
                       locked_by = NULL,
                       last_error = NULL,
                       updated_at = :now
                 WHERE id = :id
                """
            ),
            {"id": job_id, "now": datetime.now(UTC)},
        )
        await session.commit()


async def _mark_failed_or_retry(job_id: Any, attempts: int, max_attempts: int, error: str) -> None:
    now = datetime.now(UTC)
    terminal = attempts >= max_attempts
    next_status = "failed" if terminal else "pending"
    next_run_at = now if terminal else (now + compute_backoff(attempts))

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE background_jobs
                   SET status = :status,
                       locked_at = NULL,
                       locked_by = NULL,
                       finished_at = CASE WHEN :terminal THEN :now ELSE NULL END,
                       last_error = :err,
                       run_at = :next_run,
                       updated_at = :now
                 WHERE id = :id
                """
            ),
            {
                "id": job_id,
                "status": next_status,
                "terminal": terminal,
                "err": error[:4000],
                "now": now,
                "next_run": next_run_at,
            },
        )
        await session.commit()


# =============================================================================
# Run one
# =============================================================================
async def _run_one(job: dict[str, Any]) -> None:
    kind = job["kind"]
    fn = get_task(kind)
    if fn is None:
        await _mark_failed_or_retry(
            job["id"], job["attempts"], job["max_attempts"], f"unknown kind: {kind}"
        )
        log.error("kind desconhecido", kind=kind, known=known_kinds())
        return

    async with SessionLocal() as session:
        ctx = JobContext(
            session=session,
            job_id=job["id"],
            kind=kind,
            payload=job["payload"] or {},
        )
        try:
            await fn(ctx)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.exception("job falhou", job_id=str(job["id"]), kind=kind)
            await _mark_failed_or_retry(
                job["id"], job["attempts"], job["max_attempts"], repr(exc)
            )
            return

    await _mark_done(job["id"])
    log.info("job done", job_id=str(job["id"]), kind=kind)


# =============================================================================
# Loop principal
# =============================================================================
class JobRunner:
    def __init__(self, queues: list[str] | None = None) -> None:
        self._stop = asyncio.Event()
        self._queues = queues

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        await recover_stuck()
        log.info("worker pronto", worker=WORKER_ID, queues=self._queues or ["*"])

        while not self._stop.is_set():
            try:
                claimed = await claim_batch(settings.worker_batch_size, self._queues)
                if claimed:
                    await asyncio.gather(
                        *(_run_one(j) for j in claimed),
                        return_exceptions=True,
                    )
                    continue
                # nada em fila; bloqueia até o próximo poll ou sinal
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=settings.worker_poll_interval_ms / 1000,
                    )
            except Exception:  # noqa: BLE001
                log.exception("erro no loop do runner; seguindo")
                await asyncio.sleep(1)


# =============================================================================
# Signals
# =============================================================================
def install_signal_handlers(loop: asyncio.AbstractEventLoop, runner: JobRunner) -> None:
    def _handler(sig: int) -> None:
        log.info("sinal recebido — encerrando", sig=sig)
        runner.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler, sig)