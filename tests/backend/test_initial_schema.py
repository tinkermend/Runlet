from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.infrastructure.db.base import BaseModel
from app.infrastructure.db.models import assets, crawl, execution, jobs, systems  # noqa: F401


@pytest.fixture
def db_engine(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    backend_root = project_root / "backend"
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))

    db_path = tmp_path / "schema.sqlite3"
    db_url = f"sqlite:///{db_path}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "head")

    engine = create_engine(db_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_initial_schema_exposes_core_tables(db_engine):
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())
    assert table_names == {
        "alembic_version",
        "auth_states",
        "crawl_snapshots",
        "execution_plans",
        "execution_requests",
        "execution_runs",
        "intent_aliases",
        "page_assets",
        "page_checks",
        "pages",
        "queued_jobs",
        "system_credentials",
        "systems",
    }


def test_initial_schema_exposes_core_columns(db_engine):
    inspector = inspect(db_engine)

    systems_columns = {column["name"] for column in inspector.get_columns("systems")}
    assert {"code", "name", "base_url", "framework_type"} <= systems_columns

    page_assets_columns = {column["name"] for column in inspector.get_columns("page_assets")}
    assert {"system_id", "page_id", "asset_key", "asset_version", "status"} <= page_assets_columns

    execution_request_columns = {
        column["name"] for column in inspector.get_columns("execution_requests")
    }
    assert {"request_source", "system_hint", "page_hint", "check_goal"} <= execution_request_columns

    queued_job_columns = {column["name"] for column in inspector.get_columns("queued_jobs")}
    assert {"job_type", "payload", "status"} <= queued_job_columns


def test_initial_schema_matches_sqlmodel_metadata(db_engine):
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_server_default": True},
        )
        diffs = compare_metadata(context, BaseModel.metadata)

    assert diffs == []
