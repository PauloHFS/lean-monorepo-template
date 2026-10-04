"""Entrypoint do worker.

Uso:
    python -m app.worker
"""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger

# Importar tasks aqui é o que dispara `register_task(...)`
from app.jobs import tasks  # noqa: F401
from app.jobs.runner import JobRunner, install_signal_handlers

log = get_logger("worker.main")


async def main() -> None:
    runner = JobRunner(queues=None)  # None = todas as filas
    loop = asyncio.get_running_loop()
    install_signal_handlers(loop, runner)
    await runner.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("bye")
