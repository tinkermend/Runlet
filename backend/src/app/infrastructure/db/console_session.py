from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, create_engine

from app.config.settings import settings


def get_console_db() -> Iterator[Session]:
    """Sync session dependency for console endpoints.

    Uses a sync engine so it works with both PostgreSQL (production)
    and SQLite (tests via dependency_overrides).
    """
    engine = create_engine(settings.database_url.replace("+asyncpg", ""), pool_pre_ping=True)
    with Session(engine) as session:
        yield session
