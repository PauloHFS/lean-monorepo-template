"""Engine + sessionmaker async.

`get_db()` é injetado nas dependências do FastAPI: faz yield da session,
rollback se exceção e close sempre. Não commita — quem chama é responsável
pelo commit.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _make_engine() -> AsyncEngine:
    return create_async_engine(
        settings.database_url_async,
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


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
