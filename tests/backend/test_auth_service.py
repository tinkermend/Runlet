from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.systems import AuthState, SystemCredential


def _upgrade_to_head(tmp_path: Path):
    project_root = Path(__file__).resolve().parents[2]
    backend_root = project_root / "backend"
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))

    db_path = tmp_path / "auth-runtime.sqlite3"
    db_url = f"sqlite:///{db_path}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")

    return create_engine(db_url)


def test_auth_and_crawl_models_expose_runtime_fields():
    assert hasattr(SystemCredential, "login_auth_type")
    assert hasattr(AuthState, "storage_state")
    assert hasattr(AuthState, "status")
    assert hasattr(CrawlSnapshot, "quality_score")
    assert hasattr(MenuNode, "playwright_locator")
    assert hasattr(Page, "page_summary")
    assert hasattr(PageElement, "playwright_locator")
    assert hasattr(PageElement, "stability_score")
    assert hasattr(PageElement, "usage_description")
    assert hasattr(QueuedJob, "status")
    assert hasattr(QueuedJob, "created_at")
    assert hasattr(QueuedJob, "started_at")
    assert hasattr(QueuedJob, "finished_at")
    assert hasattr(QueuedJob, "failure_message")


def test_auth_and_crawl_migration_exposes_runtime_fields(tmp_path):
    engine = _upgrade_to_head(tmp_path)
    try:
        inspector = inspect(engine)

        auth_state_columns = {column["name"] for column in inspector.get_columns("auth_states")}
        assert {"storage_state", "validated_at", "expires_at", "status"} <= auth_state_columns

        crawl_snapshot_columns = {
            column["name"] for column in inspector.get_columns("crawl_snapshots")
        }
        assert {
            "quality_score",
            "degraded",
            "framework_detected",
        } <= crawl_snapshot_columns

        menu_node_columns = {column["name"] for column in inspector.get_columns("menu_nodes")}
        assert {"playwright_locator"} <= menu_node_columns

        page_columns = {column["name"] for column in inspector.get_columns("pages")}
        assert {"page_summary"} <= page_columns

        page_element_columns = {column["name"] for column in inspector.get_columns("page_elements")}
        assert {
            "playwright_locator",
            "stability_score",
            "usage_description",
        } <= page_element_columns

        queued_job_columns = {column["name"] for column in inspector.get_columns("queued_jobs")}
        assert {"status", "created_at", "started_at", "finished_at", "failure_message"} <= queued_job_columns
    finally:
        engine.dispose()
