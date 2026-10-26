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


def _make_engine() -> AsyncEngine:
    return create_async_engine(
        apply_sslmode(settings.database_url_async, settings.db_sslmode),
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
