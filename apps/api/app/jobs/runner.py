"""Entry point do worker — chamado pelo `just worker` e docker-compose.

Procrastinate: o worker async roda enquanto o App estiver aberto. O
`run_worker_async()` instala handlers de SIGINT/SIGTERM por padrão e faz
shutdown gracioso (drain) das jobs em execução.
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.jobs.app import app

log = get_logger("worker")


async def main() -> None:
    log.info("worker iniciando", queues="*")
    async with app.open_async():
        await app.run_worker_async()


if __name__ == "__main__":
    asyncio.run(main())
