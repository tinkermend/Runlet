from __future__ import annotations

DEFAULT_ALEMBIC_URL = "sqlite:///./runlet.db"


def resolve_alembic_database_url(*, configured_url: str | None, runtime_url: str | None) -> str:
    if configured_url and configured_url != DEFAULT_ALEMBIC_URL:
        return configured_url
    if runtime_url:
        return to_sync_database_url(runtime_url)
    if configured_url:
        return configured_url
    return DEFAULT_ALEMBIC_URL


def to_sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if database_url.startswith("sqlite+aiosqlite:///"):
        return database_url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return database_url
