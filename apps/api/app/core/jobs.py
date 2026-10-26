"""Rate limit por janela fixa e dead-letter queue para jobs do Procrastinate.

Ambos vivem no Postgres (AD-001). A janela é fixa e alinhada ao epoch:
`floor(epoch / window) * window`, o que torna o contador determinístico e
sem estado em memória.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

# SQL literal: valores entram só por bind params (AD-012 / anti-SQLi).
RATE_LIMIT_SQL = """
    INSERT INTO job_rate_limits (kind, key, window_start, count)
    VALUES (
        :kind,
        :key,
        to_timestamp(
            (floor(extract(epoch from now()) / :window) * :window)::double precision
        ),
        1
    )
    ON CONFLICT (kind, key, window_start)
    DO UPDATE SET count = job_rate_limits.count + 1
    RETURNING count
"""

INSERT_DEAD_LETTER_SQL = """
    INSERT INTO dead_letters (kind, key, payload, error, original_job_id)
    VALUES (:kind, :key, CAST(:payload AS jsonb), :error, :original_job_id)
    RETURNING id
"""


class JobRateLimitExceeded(Exception):
    """Levantada quando o contador da janela passa do limite configurado."""

    def __init__(self, kind: str, key: str, count: int, limit: int, window_s: int) -> None:
        self.kind = kind
        self.key = key
        self.count = count
        self.limit = limit
        self.window_s = window_s
        super().__init__(f"rate limit excedido para {kind} (key={key!r}): {count}>{limit}")


async def check_job_rate_limit(kind: str, key: str, limit: int, window_s: int) -> int:
    """Incrementa o contador da janela e levanta se passou do limite.

    Retorna a contagem atual (incluindo a tentativa) quando ainda dentro do
    limite. `limit` é o número de jobs permitidos por janela. O contador conta
    as tentativas da janela, inclusive as rejeitadas.
    """
    if window_s <= 0:
        raise ValueError("window_s deve ser positivo")
    if limit < 0:
        raise ValueError("limit não pode ser negativo")

    async with AsyncSessionLocal() as session, session.begin():
        row = (
            (
                await session.execute(
                    text(RATE_LIMIT_SQL),
                    {"kind": kind, "key": key, "window": window_s},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise RuntimeError("upsert de job_rate_limits não retornou linha")

    count = int(row["count"])
    if count > limit:
        raise JobRateLimitExceeded(kind=kind, key=key, count=count, limit=limit, window_s=window_s)
    return count


async def record_dead_letter(
    kind: str,
    key: str,
    payload: dict[str, Any],
    error: str,
    original_job_id: int | None = None,
) -> int:
    """Grava a falha em `dead_letters` e devolve o id da linha."""
    async with AsyncSessionLocal() as session, session.begin():
        row = (
            (
                await session.execute(
                    text(INSERT_DEAD_LETTER_SQL),
                    {
                        "kind": kind,
                        "key": key,
                        "payload": json.dumps(payload, default=str),
                        "error": error,
                        "original_job_id": original_job_id,
                    },
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise RuntimeError("insert de dead_letters não retornou linha")
    return int(row["id"])
