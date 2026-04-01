from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import settings


def create_db_engine(database_url: str | None = None) -> AsyncEngine:
    return create_async_engine(database_url or settings.database_url, pool_pre_ping=True)


def create_session_factory(
    database_url: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    engine = create_db_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    session_factory = create_session_factory()
    async with session_factory() as session:
        yield session
