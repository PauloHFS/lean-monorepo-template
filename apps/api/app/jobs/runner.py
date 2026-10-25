"""Entry point do worker — chamado pelo `just worker` e docker-compose.

Procrastinate: o worker async roda enquanto o App estiver aberto. O
`run_worker_async()` instala handlers de SIGINT/SIGTERM por padrão e faz
shutdown gracioso (drain) das jobs em execução.

A abertura do app (pool do Postgres) é retentada com backoff: sem isso o
worker entra em crash-loop enquanto o banco ainda está subindo.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.logging import get_logger
from app.core.observability import setup_tracing, shutdown_tracing
from app.jobs.app import app

log = get_logger("worker")

OPEN_ATTEMPTS = 10


@retry(
    stop=stop_after_attempt(OPEN_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    reraise=True,
)
async def _open_app(stack: AsyncExitStack) -> None:
    await stack.enter_async_context(app.open_async())


async def main() -> None:
    log.info("worker iniciando", queues="*")
    setup_tracing()
    try:
        async with AsyncExitStack() as stack:
            try:
                await _open_app(stack)
            except Exception:  # noqa: BLE001 — loga e deixa o container morrer
                log.error(
                    "worker: Postgres indisponível após %s tentativas; encerrando",
                    OPEN_ATTEMPTS,
                    exc_info=True,
                )
                raise
            await app.run_worker_async()
    finally:
        shutdown_tracing()


if __name__ == "__main__":
    asyncio.run(main())
