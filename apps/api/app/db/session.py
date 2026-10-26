"""Engine + sessionmaker async.

`get_db()` é injetado nas dependências do FastAPI: faz yield da session,
rollback se exceção e close sempre. Não commita — quem chama é responsável
pelo commit.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def apply_sslmode(dsn: str, sslmode: str | None) -> str:
    """Anexa/sobrescreve `sslmode` na query string preservando o resto."""
    if not sslmode:
        return dsn
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["sslmode"] = sslmode
    return urlunsplit(parts._replace(query=urlencode(query)))


def _api_dsn() -> str:
    """DSN do engine da API, com `db_sslmode` só no caminho direto.

    O pgbouncer local não termina TLS: aplicar `DB_SSLMODE=require` ao DSN do
    pooler faria o asyncpg abrir TLS contra o pgbouncer e falhar no boot. Se o
    DSN do pooler já trouxer `sslmode`, ele é respeitado (é do operador).
    """
    if settings.database_url_pooler:
        return settings.database_url_api
    return apply_sslmode(settings.database_url_api, settings.db_sslmode)


def _make_engine() -> AsyncEngine:
    return create_async_engine(
        _api_dsn(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        future=True,
        echo=False,
    )


engine: AsyncEngine = _make_engine()
SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
    class_=AsyncSession,
)
# Alias explícito para código de infraestrutura (jobs/CLI) que abre a própria
# sessão em vez de receber a dependency do FastAPI.
AsyncSessionLocal = SessionLocal


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
