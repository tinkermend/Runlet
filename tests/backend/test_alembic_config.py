from app.infrastructure.db.alembic_config import (
    DEFAULT_ALEMBIC_URL,
    resolve_alembic_database_url,
    to_sync_database_url,
)


def test_to_sync_database_url_converts_asyncpg_to_psycopg():
    assert (
        to_sync_database_url("postgresql+asyncpg://user:pass@127.0.0.1:5432/runlet")
        == "postgresql+psycopg://user:pass@127.0.0.1:5432/runlet"
    )


def test_resolve_alembic_database_url_prefers_explicit_override():
    assert (
        resolve_alembic_database_url(
            configured_url="sqlite:////tmp/test.db",
            runtime_url="postgresql+asyncpg://user:pass@127.0.0.1:5432/runlet",
        )
        == "sqlite:////tmp/test.db"
    )


def test_resolve_alembic_database_url_uses_runtime_url_when_config_is_default():
    assert (
        resolve_alembic_database_url(
            configured_url=DEFAULT_ALEMBIC_URL,
            runtime_url="postgresql+asyncpg://user:pass@127.0.0.1:5432/runlet",
        )
        == "postgresql+psycopg://user:pass@127.0.0.1:5432/runlet"
    )
