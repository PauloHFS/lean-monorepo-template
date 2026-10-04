"""Rate limit por chave (janela fixa), Postgres-only.

Uso:
    from fastapi import Depends
    from app.core.ratelimit import rate_limit

    @router.post("/login", dependencies=[Depends(rate_limit("login", limit=5, window_s=60))])
    async def login(...): ...

Algoritmo:
- chave = string qualquer; recomendado "ip:endpoint"
- INSERT ... ON CONFLICT (key) DO UPDATE reseta a janela se passou do tempo,
  senão incrementa count. Tudo em uma transação.
- O SELECT é separado para descobrir se passou do limite após o increment.
- Aceitável para volumes moderados. Se virar gargalo, mover para advisory lock.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import text

from app.db.session import SessionLocal

# SQL puro, exposto para fácil verificação em testes unitários.
HIT_SQL = """
    INSERT INTO rate_limits (key, count, window_start)
    VALUES (:key, 1, :now)
    ON CONFLICT (key) DO UPDATE
       SET count        = CASE
                            WHEN rate_limits.window_start < :window_start_min
                            THEN 1
                            ELSE rate_limits.count + 1
                          END,
           window_start = CASE
                            WHEN rate_limits.window_start < :window_start_min
                            THEN :now
                            ELSE rate_limits.window_start
                          END
    RETURNING count, window_start
"""


async def hit(key: str, limit: int, window_s: int) -> tuple[int, datetime]:
    """Registra uma tentativa e devolve (count_atual, window_start)."""
    now = datetime.now(UTC)
    window_start_min = now.timestamp() - window_s
    async with SessionLocal() as session, session.begin():
        row = (
            await session.execute(
                text(HIT_SQL),
                {
                    "key": key,
                    "now": now,
                    "window_start_min": datetime.fromtimestamp(window_start_min, tz=UTC),
                },
            )
            .mappings()
            .first()
        )
    return int(row["count"]), row["window_start"]


def rate_limit(
    endpoint: str, *, limit: int = 60, window_s: int = 60
) -> Callable[..., Awaitable[None]]:
    """Dependency FastAPI que limita por IP+endpoint."""

    async def _dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{endpoint}"
        count, _ = await hit(key, limit=limit, window_s=window_s)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(window_s)},
            )

    return _dep