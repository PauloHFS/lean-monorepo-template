"""Logging estruturado (JSON em prod, console em dev).

Configura o stdlib logging + structlog para que os logs saiam
no formato escolhido pelo operador.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    json_mode = settings.is_prod

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        # Produção: uma linha JSON por evento, ideal para agregadores
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        # Dev: colorido, legível
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Silencia bibliotecas muito barulhentas
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "httpx"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


_configure_logging()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
