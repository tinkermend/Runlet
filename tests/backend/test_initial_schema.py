from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
    assert {"systems", "page_assets", "page_checks", "execution_requests", "queued_jobs"} <= table_names


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
