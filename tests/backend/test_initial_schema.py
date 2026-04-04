from pathlib import Path
import re
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlmodel import Session, create_engine, inspect

from app.infrastructure.db.base import BaseModel
from app.infrastructure.db.models import assets, crawl, execution, jobs, runtime_policies, systems  # noqa: F401


@pytest.fixture
def inspector(db_engine):
    return inspect(db_engine)


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
        "execution_artifacts",
        "execution_plans",
        "execution_requests",
        "execution_runs",
        "asset_reconciliation_audits",
        "intent_aliases",
        "job_runs",
        "menu_nodes",
        "module_plans",
        "page_assets",
        "page_checks",
        "page_elements",
        "pages",
        "published_jobs",
        "queued_jobs",
        "script_renders",
        "system_auth_policies",
        "system_crawl_policies",
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
        "drift_status",
        "lifecycle_status",
        "retired_reason",
        "retired_at",
        "retired_by_snapshot_id",
        "compiled_from_snapshot_id",
    } <= page_assets_columns

    page_checks_columns = {column["name"] for column in inspector.get_columns("page_checks")}
    assert {
        "lifecycle_status",
        "retired_reason",
        "retired_at",
        "retired_by_snapshot_id",
        "blocking_dependency_json",
    } <= page_checks_columns

    intent_aliases_columns = {column["name"] for column in inspector.get_columns("intent_aliases")}
    assert {
        "is_active",
        "disabled_reason",
        "disabled_at",
        "disabled_by_snapshot_id",
    } <= intent_aliases_columns

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

    execution_run_columns = {column["name"] for column in inspector.get_columns("execution_runs")}
    assert {
        "execution_plan_id",
        "status",
        "duration_ms",
        "auth_status",
        "failure_category",
        "asset_version",
        "snapshot_version",
        "created_at",
    } <= execution_run_columns
    execution_run_created_at = next(
        column for column in inspector.get_columns("execution_runs") if column["name"] == "created_at"
    )
    assert execution_run_created_at["nullable"] is False

    execution_artifact_columns = {
        column["name"] for column in inspector.get_columns("execution_artifacts")
    }
    assert {
        "execution_run_id",
        "artifact_kind",
        "result_status",
        "payload",
        "artifact_uri",
        "created_at",
    } <= execution_artifact_columns

    script_render_columns = {column["name"] for column in inspector.get_columns("script_renders")}
    assert {
        "execution_artifact_id",
        "execution_plan_id",
        "render_mode",
        "render_result",
        "script_body",
        "render_metadata",
        "created_at",
    } <= script_render_columns

    queued_job_columns = {column["name"] for column in inspector.get_columns("queued_jobs")}
    assert {
        "job_type",
        "payload",
        "result_payload",
        "policy_id",
        "trigger_source",
        "scheduled_at",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "failure_message",
    } <= queued_job_columns

    published_job_columns = {column["name"] for column in inspector.get_columns("published_jobs")}
    assert {
        "job_key",
        "page_check_id",
        "script_render_id",
        "asset_version",
        "runtime_policy",
        "schedule_expr",
        "timezone",
        "state",
        "pause_reason",
        "paused_by_snapshot_id",
        "paused_by_asset_id",
        "paused_by_page_check_id",
        "created_at",
        "updated_at",
    } <= published_job_columns


def test_execution_requests_table_contains_template_columns(inspector):
    columns = {column["name"] for column in inspector.get_columns("execution_requests")}
    assert {"template_code", "template_version", "carrier_hint", "template_params"} <= columns


def test_extended_schema_columns_present(inspector):
    reconciliation_audit_columns = {
        column["name"] for column in inspector.get_columns("asset_reconciliation_audits")
    }
    assert {
        "snapshot_id",
        "retired_asset_ids",
        "retired_check_ids",
        "disabled_alias_ids",
        "retire_reasons",
        "paused_published_job_ids",
        "created_at",
    } <= reconciliation_audit_columns

    job_run_columns = {column["name"] for column in inspector.get_columns("job_runs")}
    assert {
        "published_job_id",
        "execution_run_id",
        "policy_id",
        "trigger_source",
        "run_status",
        "scheduled_at",
        "started_at",
        "finished_at",
        "failure_message",
    } <= job_run_columns

    auth_state_columns = {column["name"] for column in inspector.get_columns("auth_states")}
    assert {"storage_state", "validated_at", "expires_at", "status"} <= auth_state_columns

    crawl_snapshot_columns = {column["name"] for column in inspector.get_columns("crawl_snapshots")}
    assert {
        "framework_detected",
        "quality_score",
        "degraded",
        "failure_reason",
        "warning_messages",
    } <= crawl_snapshot_columns

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


def test_page_elements_table_has_locator_candidates_and_state_context(inspector):
    columns = {column["name"] for column in inspector.get_columns("page_elements")}
    assert {"state_signature", "state_context", "locator_candidates"} <= columns


def test_execution_run_created_at_migration_backfills_from_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    backend_root = project_root / "backend"
    alembic_cfg = Config(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))

    db_path = tmp_path / "execution-run-created-at.sqlite3"
    db_url = f"sqlite:///{db_path}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "0008_crawl_failure_metadata")

    engine = create_engine(db_url)
    request_id = "11111111-1111-4111-8111-111111111111"
    plan_id = "22222222-2222-4222-8222-222222222222"
    earlier_run_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    later_run_id = "00000000-0000-4000-8000-000000000001"

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO execution_requests (
                    id, request_source, system_hint, page_hint, check_goal, strictness, time_budget_ms
                ) VALUES (
                    :id, 'api', 'ERP', '用户管理', 'table_render', 'balanced', 20000
                )
                """
            ),
            {"id": request_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO execution_plans (
                    id, execution_request_id, resolved_system_id, resolved_page_asset_id,
                    resolved_page_check_id, execution_track, auth_policy, module_plan_id
                ) VALUES (
                    :id, :execution_request_id, NULL, NULL, NULL, 'precompiled', 'server_injected', NULL
                )
                """
            ),
            {"id": plan_id, "execution_request_id": request_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO execution_runs (
                    id, execution_plan_id, status, duration_ms, auth_status,
                    failure_category, asset_version, snapshot_version
                ) VALUES (
                    :id, :execution_plan_id, 'failed', 100, 'blocked',
                    'assertion_failed', NULL, NULL
                )
                """
            ),
            {"id": earlier_run_id, "execution_plan_id": plan_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO execution_runs (
                    id, execution_plan_id, status, duration_ms, auth_status,
                    failure_category, asset_version, snapshot_version
                ) VALUES (
                    :id, :execution_plan_id, 'passed', 200, 'reused',
                    NULL, NULL, NULL
                )
                """
            ),
            {"id": later_run_id, "execution_plan_id": plan_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO execution_artifacts (
                    id, execution_run_id, artifact_kind, result_status, payload, artifact_uri, created_at
                ) VALUES (
                    '33333333-3333-4333-8333-333333333333',
                    :execution_run_id,
                    'module_execution',
                    'failed',
                    '{}',
                    NULL,
                    '2026-04-03 12:00:00+00:00'
                )
                """
            ),
            {"execution_run_id": earlier_run_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO execution_artifacts (
                    id, execution_run_id, artifact_kind, result_status, payload, artifact_uri, created_at
                ) VALUES (
                    '44444444-4444-4444-8444-444444444444',
                    :execution_run_id,
                    'module_execution',
                    'success',
                    '{}',
                    NULL,
                    '2026-04-03 12:05:00+00:00'
                )
                """
            ),
            {"execution_run_id": later_run_id},
        )

    command.upgrade(alembic_cfg, "head")

    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT id, created_at
                FROM execution_runs
                ORDER BY created_at ASC, id ASC
                """
            )
        ).all()

    engine.dispose()

    assert len(rows) == 2
    assert rows[0].id == earlier_run_id
    assert rows[1].id == later_run_id
    assert str(rows[0].created_at).startswith("2026-04-03 12:00:00")
    assert str(rows[1].created_at).startswith("2026-04-03 12:05:00")


def test_runtime_datetime_columns_are_timezone_aware_in_metadata():
    runtime_columns = [
        BaseModel.metadata.tables["execution_runs"].c["created_at"],
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


def test_asset_lifecycle_datetime_columns_are_timezone_aware_in_metadata():
    lifecycle_columns = [
        BaseModel.metadata.tables["page_assets"].c["retired_at"],
        BaseModel.metadata.tables["page_checks"].c["retired_at"],
        BaseModel.metadata.tables["intent_aliases"].c["disabled_at"],
    ]

    assert all(column.type.timezone is True for column in lifecycle_columns)


def test_runtime_policy_tables_exist(inspector):
    table_names = set(inspector.get_table_names())
    assert "system_auth_policies" in table_names
    assert "system_crawl_policies" in table_names

    auth_policy_columns = {column["name"] for column in inspector.get_columns("system_auth_policies")}
    assert {
        "system_id",
        "enabled",
        "state",
        "schedule_expr",
        "auth_mode",
        "captcha_provider",
        "last_triggered_at",
        "last_succeeded_at",
        "last_failed_at",
        "last_failure_message",
    } <= auth_policy_columns

    crawl_policy_columns = {column["name"] for column in inspector.get_columns("system_crawl_policies")}
    assert {
        "system_id",
        "enabled",
        "state",
        "schedule_expr",
        "crawl_scope",
        "last_triggered_at",
        "last_succeeded_at",
        "last_failed_at",
        "last_failure_message",
    } <= crawl_policy_columns

    auth_policy_indexes = inspector.get_indexes("system_auth_policies")
    assert any(
        index["name"] == "ix_system_auth_policies_system_id" and bool(index.get("unique"))
        for index in auth_policy_indexes
    )
    crawl_policy_indexes = inspector.get_indexes("system_crawl_policies")
    assert any(
        index["name"] == "ix_system_crawl_policies_system_id" and bool(index.get("unique"))
        for index in crawl_policy_indexes
    )


def test_page_asset_and_related_tables_expose_lifecycle_columns(db_engine):
    inspector = inspect(db_engine)

    page_assets_columns = {column["name"] for column in inspector.get_columns("page_assets")}
    assert {
        "drift_status",
        "lifecycle_status",
        "retired_reason",
        "retired_at",
        "retired_by_snapshot_id",
    } <= page_assets_columns

    page_checks_columns = {column["name"] for column in inspector.get_columns("page_checks")}
    assert {
        "lifecycle_status",
        "retired_reason",
        "retired_at",
        "retired_by_snapshot_id",
        "blocking_dependency_json",
    } <= page_checks_columns

    intent_aliases_columns = {column["name"] for column in inspector.get_columns("intent_aliases")}
    assert {
        "is_active",
        "disabled_reason",
        "disabled_at",
        "disabled_by_snapshot_id",
    } <= intent_aliases_columns

    published_job_columns = {column["name"] for column in inspector.get_columns("published_jobs")}
    assert {
        "pause_reason",
        "paused_by_snapshot_id",
        "paused_by_asset_id",
        "paused_by_page_check_id",
    } <= published_job_columns


def test_initial_schema_exposes_reconciliation_audit_table(db_engine):
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())
    assert "asset_reconciliation_audits" in table_names

    reconciliation_audit_columns = {
        column["name"] for column in inspector.get_columns("asset_reconciliation_audits")
    }
    assert {
        "snapshot_id",
        "retired_asset_ids",
        "retired_check_ids",
        "disabled_alias_ids",
        "retire_reasons",
        "paused_published_job_ids",
        "created_at",
    } <= reconciliation_audit_columns

    auth_policy_foreign_keys = inspector.get_foreign_keys("system_auth_policies")
    assert any(
        fk["referred_table"] == "systems"
        and fk["constrained_columns"] == ["system_id"]
        and fk["referred_columns"] == ["id"]
        for fk in auth_policy_foreign_keys
    )
    crawl_policy_foreign_keys = inspector.get_foreign_keys("system_crawl_policies")
    assert any(
        fk["referred_table"] == "systems"
        and fk["constrained_columns"] == ["system_id"]
        and fk["referred_columns"] == ["id"]
        for fk in crawl_policy_foreign_keys
    )


def test_reconciliation_audit_persists_non_empty_identifier_lists(db_engine):
    from app.infrastructure.db.models.assets import AssetReconciliationAudit
    from app.infrastructure.db.models.crawl import CrawlSnapshot
    from app.infrastructure.db.models.systems import System

    retired_asset_id = uuid4()
    retired_check_id = uuid4()
    alias_id = uuid4()
    enabled_alias_id = uuid4()
    paused_job_id = uuid4()
    resumed_job_id = uuid4()

    with Session(db_engine) as session:
        system = System(
            code="audit",
            name="Audit",
            base_url="https://audit.example.com",
            framework_type="react",
        )
        session.add(system)
        session.flush()

        snapshot = CrawlSnapshot(
            system_id=system.id,
            crawl_type="full",
            framework_detected=system.framework_type,
        )
        session.add(snapshot)
        session.flush()

        audit = AssetReconciliationAudit(
            snapshot_id=snapshot.id,
            retired_asset_ids=[retired_asset_id],
            retired_check_ids=[retired_check_id],
            disabled_alias_ids=[alias_id],
            enabled_alias_ids=[enabled_alias_id],
            retire_reasons=[{"category": "retired_missing", "asset_id": str(retired_asset_id)}],
            paused_published_job_ids=[paused_job_id],
            resumed_published_job_ids=[resumed_job_id],
        )
        session.add(audit)
        session.commit()
        session.refresh(audit)

        assert audit.retired_asset_ids == [str(retired_asset_id)]
        assert audit.retired_check_ids == [str(retired_check_id)]
        assert audit.disabled_alias_ids == [str(alias_id)]
        assert audit.enabled_alias_ids == [str(enabled_alias_id)]
        assert audit.paused_published_job_ids == [str(paused_job_id)]
        assert audit.resumed_published_job_ids == [str(resumed_job_id)]


def test_runtime_policy_models_expose_expected_fields():
    from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy

    assert SystemAuthPolicy.__tablename__ == "system_auth_policies"
    assert SystemCrawlPolicy.__tablename__ == "system_crawl_policies"

    assert {
        "system_id",
        "schedule_expr",
        "last_triggered_at",
        "last_succeeded_at",
        "last_failed_at",
        "last_failure_message",
    } <= set(SystemAuthPolicy.model_fields)
    assert {"system_id", "crawl_scope", "enabled"} <= set(SystemCrawlPolicy.model_fields)
    assert SystemAuthPolicy.model_fields["enabled"].default is True
    assert SystemAuthPolicy.model_fields["state"].default == "active"
    assert SystemAuthPolicy.model_fields["captcha_provider"].default == "ddddocr"
    assert SystemCrawlPolicy.model_fields["enabled"].default is True
    assert SystemCrawlPolicy.model_fields["state"].default == "active"
    assert SystemCrawlPolicy.model_fields["crawl_scope"].default == "full"

    auth_table_columns = set(SystemAuthPolicy.__table__.columns.keys())
    crawl_table_columns = set(SystemCrawlPolicy.__table__.columns.keys())
    assert {
        "id",
        "system_id",
        "schedule_expr",
        "last_triggered_at",
        "last_succeeded_at",
        "last_failed_at",
        "last_failure_message",
    } <= auth_table_columns
    assert {
        "id",
        "system_id",
        "crawl_scope",
        "last_triggered_at",
        "last_succeeded_at",
        "last_failed_at",
        "last_failure_message",
    } <= crawl_table_columns


def test_alembic_revision_ids_fit_version_table_limit():
    project_root = Path(__file__).resolve().parents[2]
    versions_dir = project_root / "backend" / "alembic" / "versions"
    revision_pattern = re.compile(r'^revision\s*=\s*"([^"]+)"', re.MULTILINE)

    revision_ids: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        match = revision_pattern.search(path.read_text(encoding="utf-8"))
        assert match is not None, f"missing revision id in {path.name}"
        revision_ids.append(match.group(1))

    assert revision_ids
    assert all(len(revision_id) <= 32 for revision_id in revision_ids)
