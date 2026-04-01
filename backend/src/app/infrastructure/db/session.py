from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.config.settings import settings


def to_sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return database_url


def create_db_engine(database_url: str | None = None):
    resolved_url = to_sync_database_url(database_url or settings.database_url)
    return create_engine(resolved_url, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    engine = create_db_engine()
    with Session(engine) as session:
        yield session
