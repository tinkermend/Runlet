from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import settings


_default_engine: AsyncEngine | None = None
_default_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_db_engine(database_url: str | None = None) -> AsyncEngine:
    global _default_engine

    if database_url is not None:
        return create_async_engine(database_url, pool_pre_ping=True)

    if _default_engine is None:
        _default_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _default_engine


def create_session_factory(
    database_url: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    global _default_session_factory

    if database_url is not None:
        return async_sessionmaker(create_db_engine(database_url), expire_on_commit=False)

    if _default_session_factory is None:
        _default_session_factory = async_sessionmaker(
            create_db_engine(),
            expire_on_commit=False,
        )
    return _default_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    session_factory = create_session_factory()
    async with session_factory() as session:
        yield session
