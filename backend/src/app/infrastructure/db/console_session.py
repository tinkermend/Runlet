from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, create_engine

from app.config.settings import settings
from app.infrastructure.db.alembic_config import to_sync_database_url
from app.infrastructure.db import models as _models  # noqa: F401


def _build_console_sync_database_url(database_url: str) -> str:
    return to_sync_database_url(database_url)


def get_console_db() -> Iterator[Session]:
    """Sync session dependency for console endpoints.

    Uses a sync engine so it works with both PostgreSQL (production)
    and SQLite (tests via dependency_overrides).
    """
    engine = create_engine(
        _build_console_sync_database_url(settings.database_url),
        pool_pre_ping=True,
    )
    with Session(engine) as session:
        yield session
