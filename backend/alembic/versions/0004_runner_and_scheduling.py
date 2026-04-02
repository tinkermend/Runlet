"""runner and scheduling schema

Revision ID: 0004_runner_and_scheduling
Revises: 0003_asset_compiler_and_drift
Create Date: 2026-04-02 18:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_runner_and_scheduling"
down_revision = "0003_asset_compiler_and_drift"
branch_labels = None
depends_on = None


execution_result_status = sa.Enum(
    "pending",
    "success",
    "failed",
    name="execution_result_status",
    native_enum=False,
)

render_result_status = sa.Enum(
    "pending",
    "success",
    "failed",
    name="render_result_status",
    native_enum=False,
)

published_job_state = sa.Enum(
    "active",
    "paused",
    "archived",
    name="published_job_state",
    native_enum=False,
)

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "execution_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=64), nullable=False),
        sa.Column("result_status", execution_result_status, nullable=False),
        sa.Column("payload", json_type, nullable=True),
        sa.Column("artifact_uri", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
    )
    op.create_index(
        "ix_execution_artifacts_execution_run_id",
        "execution_artifacts",
        ["execution_run_id"],
        unique=False,
    )

    op.create_table(
        "script_renders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("execution_plan_id", sa.Uuid(), nullable=True),
        sa.Column("render_mode", sa.String(length=32), nullable=False),
        sa.Column("render_result", render_result_status, nullable=False),
        sa.Column("script_body", sa.Text(), nullable=True),
        sa.Column("render_metadata", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_artifact_id"], ["execution_artifacts.id"]),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["execution_plans.id"]),
    )
    op.create_index(
        "ix_script_renders_execution_artifact_id",
        "script_renders",
        ["execution_artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_script_renders_execution_plan_id",
        "script_renders",
        ["execution_plan_id"],
        unique=False,
    )

    op.create_table(
        "published_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_key", sa.String(length=128), nullable=False),
        sa.Column("page_check_id", sa.Uuid(), nullable=False),
        sa.Column("script_render_id", sa.Uuid(), nullable=True),
        sa.Column("asset_version", sa.String(length=64), nullable=True),
        sa.Column("runtime_policy", sa.String(length=64), nullable=False),
        sa.Column("schedule_expr", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("state", published_job_state, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["page_check_id"], ["page_checks.id"]),
        sa.ForeignKeyConstraint(["script_render_id"], ["script_renders.id"]),
    )
    op.create_index("ix_published_jobs_job_key", "published_jobs", ["job_key"], unique=True)
    op.create_index(
        "ix_published_jobs_page_check_id",
        "published_jobs",
        ["page_check_id"],
        unique=False,
    )
    op.create_index(
        "ix_published_jobs_script_render_id",
        "published_jobs",
        ["script_render_id"],
        unique=False,
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("published_job_id", sa.Uuid(), nullable=False),
        sa.Column("execution_run_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_source", sa.String(length=32), nullable=False),
        sa.Column("run_status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["published_job_id"], ["published_jobs.id"]),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
    )
    op.create_index("ix_job_runs_published_job_id", "job_runs", ["published_job_id"], unique=False)
    op.create_index("ix_job_runs_execution_run_id", "job_runs", ["execution_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_runs_execution_run_id", table_name="job_runs")
    op.drop_index("ix_job_runs_published_job_id", table_name="job_runs")
    op.drop_table("job_runs")

    op.drop_index("ix_published_jobs_script_render_id", table_name="published_jobs")
    op.drop_index("ix_published_jobs_page_check_id", table_name="published_jobs")
    op.drop_index("ix_published_jobs_job_key", table_name="published_jobs")
    op.drop_table("published_jobs")

    op.drop_index("ix_script_renders_execution_plan_id", table_name="script_renders")
    op.drop_index("ix_script_renders_execution_artifact_id", table_name="script_renders")
    op.drop_table("script_renders")

    op.drop_index("ix_execution_artifacts_execution_run_id", table_name="execution_artifacts")
    op.drop_table("execution_artifacts")
