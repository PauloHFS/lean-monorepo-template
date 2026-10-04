"""Cache key/value em `kv_cache` (Postgres-only, sem Redis).

- `get(key)`: retorna o valor se existir e não estiver expirado; caso contrário None.
- `set(key, value, ttl_s=None)`: upsert com TTL opcional.
- `delete(key)`: remove.

`value` é qualquer coisa serializável em JSON (dict, list, str, int, float, bool, None).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.db.session import SessionLocal

# SQL exposto para testabilidade: testa-se a string, não o resultado.
GET_SQL = """
    SELECT value
      FROM kv_cache
     WHERE key = :key
       AND (expires_at IS NULL OR expires_at > :now)
"""

UPSERT_SQL = """
    INSERT INTO kv_cache (key, value, expires_at)
    VALUES (:key, :value::jsonb, :expires_at)
    ON CONFLICT (key) DO UPDATE
       SET value      = EXCLUDED.value,
           expires_at = EXCLUDED.expires_at
"""

DELETE_SQL = "DELETE FROM kv_cache WHERE key = :key"


async def get(key: str) -> Any | None:
    async with SessionLocal() as session:
        row = (
            await session.execute(text(GET_SQL), {"key": key, "now": datetime.now(UTC)})
            .mappings()
            .first()
        )
    if not row:
        return None
    raw = row["value"]
    # psycopg/asyncpg já desserializa JSONB → dict; mas aceitamos string por garantia
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


async def set(key: str, value: Any, ttl_s: int | None = None) -> None:
    expires_at = (
        (datetime.now(UTC) + timedelta(seconds=ttl_s)) if ttl_s is not None else None
    )
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text(UPSERT_SQL),
            {"key": key, "value": json.dumps(value), "expires_at": expires_at},
        )


async def delete(key: str) -> None:
    async with SessionLocal() as session, session.begin():
        await session.execute(text(DELETE_SQL), {"key": key})