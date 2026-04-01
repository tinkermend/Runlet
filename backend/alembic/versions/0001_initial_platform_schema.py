"""initial platform schema

Revision ID: 0001_initial_platform_schema
Revises:
Create Date: 2026-04-01 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_platform_schema"
down_revision = None
branch_labels = None
depends_on = None


asset_status = sa.Enum(
    "draft",
    "ready",
    "suspect",
    "stale",
    "disabled",
    name="asset_status",
    native_enum=False,
)

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "systems",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("framework_type", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_systems_code", "systems", ["code"], unique=True)

    op.create_table(
        "system_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("login_url", sa.String(length=512), nullable=False),
        sa.Column("login_username_encrypted", sa.Text(), nullable=False),
        sa.Column("login_password_encrypted", sa.Text(), nullable=False),
        sa.Column("login_auth_type", sa.String(length=32), nullable=False),
        sa.Column("login_selectors", json_type, nullable=True),
        sa.Column("secret_ref", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index("ix_system_credentials_system_id", "system_credentials", ["system_id"], unique=False)

    op.create_table(
        "auth_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("storage_state", json_type, nullable=True),
        sa.Column("cookies", json_type, nullable=True),
        sa.Column("local_storage", json_type, nullable=True),
        sa.Column("session_storage", json_type, nullable=True),
        sa.Column("token_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index("ix_auth_states_system_id", "auth_states", ["system_id"], unique=False)

    op.create_table(
        "crawl_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_type", sa.String(length=32), nullable=False),
        sa.Column("framework_detected", sa.String(length=32), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("structure_hash", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index("ix_crawl_snapshots_system_id", "crawl_snapshots", ["system_id"], unique=False)

    op.create_table(
        "pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("route_path", sa.String(length=512), nullable=False),
        sa.Column("page_title", sa.String(length=255), nullable=True),
        sa.Column("page_summary", sa.Text(), nullable=True),
        sa.Column("keywords", json_type, nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["crawl_snapshots.id"]),
    )
    op.create_index("ix_pages_system_id", "pages", ["system_id"], unique=False)
    op.create_index("ix_pages_snapshot_id", "pages", ["snapshot_id"], unique=False)

    op.create_table(
        "page_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column("asset_version", sa.String(length=64), nullable=False),
        sa.Column("status", asset_status, nullable=False),
        sa.Column("compiled_from_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"]),
        sa.ForeignKeyConstraint(["compiled_from_snapshot_id"], ["crawl_snapshots.id"]),
    )
    op.create_index("ix_page_assets_system_id", "page_assets", ["system_id"], unique=False)
    op.create_index("ix_page_assets_page_id", "page_assets", ["page_id"], unique=False)
    op.create_index("ix_page_assets_asset_key", "page_assets", ["asset_key"], unique=False)

    op.create_table(
        "page_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_asset_id", sa.Uuid(), nullable=False),
        sa.Column("check_code", sa.String(length=64), nullable=False),
        sa.Column("goal", sa.String(length=64), nullable=False),
        sa.Column("input_schema", json_type, nullable=True),
        sa.Column("assertion_schema", json_type, nullable=True),
        sa.Column("module_plan_id", sa.Uuid(), nullable=True),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["page_asset_id"], ["page_assets.id"]),
    )
    op.create_index("ix_page_checks_page_asset_id", "page_checks", ["page_asset_id"], unique=False)

    op.create_table(
        "intent_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_alias", sa.String(length=255), nullable=False),
        sa.Column("page_alias", sa.String(length=255), nullable=True),
        sa.Column("check_alias", sa.String(length=64), nullable=False),
        sa.Column("route_hint", sa.String(length=512), nullable=True),
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
    )

    op.create_table(
        "execution_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_source", sa.String(length=32), nullable=False),
        sa.Column("system_hint", sa.String(length=255), nullable=False),
        sa.Column("page_hint", sa.String(length=255), nullable=True),
        sa.Column("check_goal", sa.String(length=64), nullable=False),
        sa.Column("strictness", sa.String(length=32), nullable=False),
        sa.Column("time_budget_ms", sa.Integer(), nullable=False),
    )

    op.create_table(
        "execution_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_request_id", sa.Uuid(), nullable=False),
        sa.Column("resolved_system_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_page_asset_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_page_check_id", sa.Uuid(), nullable=True),
        sa.Column("execution_track", sa.String(length=32), nullable=False),
        sa.Column("auth_policy", sa.String(length=64), nullable=False),
        sa.Column("module_plan_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["execution_request_id"], ["execution_requests.id"]),
        sa.ForeignKeyConstraint(["resolved_system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["resolved_page_asset_id"], ["page_assets.id"]),
        sa.ForeignKeyConstraint(["resolved_page_check_id"], ["page_checks.id"]),
    )
    op.create_index(
        "ix_execution_plans_execution_request_id",
        "execution_plans",
        ["execution_request_id"],
        unique=False,
    )
    op.create_index("ix_execution_plans_resolved_system_id", "execution_plans", ["resolved_system_id"], unique=False)
    op.create_index(
        "ix_execution_plans_resolved_page_asset_id",
        "execution_plans",
        ["resolved_page_asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_execution_plans_resolved_page_check_id",
        "execution_plans",
        ["resolved_page_check_id"],
        unique=False,
    )

    op.create_table(
        "execution_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("auth_status", sa.String(length=32), nullable=True),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("asset_version", sa.String(length=64), nullable=True),
        sa.Column("snapshot_version", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["execution_plans.id"]),
    )
    op.create_index(
        "ix_execution_runs_execution_plan_id",
        "execution_runs",
        ["execution_plan_id"],
        unique=False,
    )

    op.create_table(
        "queued_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_queued_jobs_job_type", "queued_jobs", ["job_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_queued_jobs_job_type", table_name="queued_jobs")
    op.drop_table("queued_jobs")

    op.drop_index("ix_execution_runs_execution_plan_id", table_name="execution_runs")
    op.drop_table("execution_runs")

    op.drop_index("ix_execution_plans_resolved_page_check_id", table_name="execution_plans")
    op.drop_index("ix_execution_plans_resolved_page_asset_id", table_name="execution_plans")
    op.drop_index("ix_execution_plans_resolved_system_id", table_name="execution_plans")
    op.drop_index("ix_execution_plans_execution_request_id", table_name="execution_plans")
    op.drop_table("execution_plans")

    op.drop_table("execution_requests")

    op.drop_table("intent_aliases")

    op.drop_index("ix_page_checks_page_asset_id", table_name="page_checks")
    op.drop_table("page_checks")

    op.drop_index("ix_page_assets_asset_key", table_name="page_assets")
    op.drop_index("ix_page_assets_page_id", table_name="page_assets")
    op.drop_index("ix_page_assets_system_id", table_name="page_assets")
    op.drop_table("page_assets")

    op.drop_index("ix_pages_snapshot_id", table_name="pages")
    op.drop_index("ix_pages_system_id", table_name="pages")
    op.drop_table("pages")

    op.drop_index("ix_crawl_snapshots_system_id", table_name="crawl_snapshots")
    op.drop_table("crawl_snapshots")

    op.drop_index("ix_auth_states_system_id", table_name="auth_states")
    op.drop_table("auth_states")

    op.drop_index("ix_system_credentials_system_id", table_name="system_credentials")
    op.drop_table("system_credentials")

    op.drop_index("ix_systems_code", table_name="systems")
    op.drop_table("systems")
