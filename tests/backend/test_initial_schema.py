from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlmodel import create_engine, inspect

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
        "asset_snapshots",
        "auth_states",
        "crawl_snapshots",
        "execution_plans",
        "execution_requests",
        "execution_runs",
        "intent_aliases",
        "menu_nodes",
        "module_plans",
        "page_assets",
        "page_checks",
        "page_elements",
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
    assert {
        "system_id",
        "page_id",
        "asset_key",
        "asset_version",
        "status",
        "compiled_from_snapshot_id",
    } <= page_assets_columns

    module_plan_columns = {column["name"] for column in inspector.get_columns("module_plans")}
    assert {"page_asset_id", "check_code", "plan_version", "steps_json"} <= module_plan_columns

    asset_snapshot_columns = {column["name"] for column in inspector.get_columns("asset_snapshots")}
    assert {
        "page_asset_id",
        "crawl_snapshot_id",
        "navigation_hash",
        "key_locator_hash",
        "semantic_summary_hash",
        "diff_score_vs_previous",
        "status",
    } <= asset_snapshot_columns

    execution_request_columns = {
        column["name"] for column in inspector.get_columns("execution_requests")
    }
    assert {"request_source", "system_hint", "page_hint", "check_goal"} <= execution_request_columns

    queued_job_columns = {column["name"] for column in inspector.get_columns("queued_jobs")}
    assert {
        "job_type",
        "payload",
        "result_payload",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "failure_message",
    } <= queued_job_columns

    auth_state_columns = {column["name"] for column in inspector.get_columns("auth_states")}
    assert {"storage_state", "validated_at", "expires_at", "status"} <= auth_state_columns

    menu_node_columns = {column["name"] for column in inspector.get_columns("menu_nodes")}
    assert {"system_id", "snapshot_id", "label", "playwright_locator"} <= menu_node_columns

    page_columns = {column["name"] for column in inspector.get_columns("pages")}
    assert {"route_path", "page_summary"} <= page_columns

    page_element_columns = {column["name"] for column in inspector.get_columns("page_elements")}
    assert {"page_id", "playwright_locator", "stability_score", "usage_description"} <= page_element_columns


def test_initial_schema_matches_sqlmodel_metadata(db_engine):
    with db_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_server_default": True},
        )
        diffs = compare_metadata(context, BaseModel.metadata)

    assert diffs == []


def test_runtime_datetime_columns_are_timezone_aware_in_metadata():
    runtime_columns = [
        BaseModel.metadata.tables["queued_jobs"].c["created_at"],
        BaseModel.metadata.tables["queued_jobs"].c["started_at"],
        BaseModel.metadata.tables["queued_jobs"].c["finished_at"],
        BaseModel.metadata.tables["auth_states"].c["validated_at"],
        BaseModel.metadata.tables["auth_states"].c["expires_at"],
        BaseModel.metadata.tables["crawl_snapshots"].c["started_at"],
        BaseModel.metadata.tables["crawl_snapshots"].c["finished_at"],
        BaseModel.metadata.tables["pages"].c["crawled_at"],
    ]

    assert all(column.type.timezone is True for column in runtime_columns)
