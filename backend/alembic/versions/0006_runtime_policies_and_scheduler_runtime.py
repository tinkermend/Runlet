"""runtime policies and scheduler runtime

Revision ID: 0006_runtime_policies_and_scheduler_runtime
Revises: 0005_job_run_audit_linkage
Create Date: 2026-04-02 21:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_runtime_policies_and_scheduler_runtime"
down_revision = "0005_job_run_audit_linkage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_auth_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("schedule_expr", sa.String(length=255), nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("captcha_provider", sa.String(length=64), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index(
        "ix_system_auth_policies_system_id",
        "system_auth_policies",
        ["system_id"],
        unique=True,
    )

    op.create_table(
        "system_crawl_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("schedule_expr", sa.String(length=255), nullable=False),
        sa.Column("crawl_scope", sa.String(length=32), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index(
        "ix_system_crawl_policies_system_id",
        "system_crawl_policies",
        ["system_id"],
        unique=True,
    )

    with op.batch_alter_table("queued_jobs") as batch_op:
        batch_op.add_column(sa.Column("policy_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("trigger_source", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_queued_jobs_policy_id", ["policy_id"], unique=False)

    with op.batch_alter_table("job_runs") as batch_op:
        batch_op.add_column(sa.Column("policy_id", sa.Uuid(), nullable=True))
        batch_op.create_index("ix_job_runs_policy_id", ["policy_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_runs") as batch_op:
        batch_op.drop_index("ix_job_runs_policy_id")
        batch_op.drop_column("policy_id")

    with op.batch_alter_table("queued_jobs") as batch_op:
        batch_op.drop_index("ix_queued_jobs_policy_id")
        batch_op.drop_column("scheduled_at")
        batch_op.drop_column("trigger_source")
        batch_op.drop_column("policy_id")

    op.drop_index("ix_system_crawl_policies_system_id", table_name="system_crawl_policies")
    op.drop_table("system_crawl_policies")

    op.drop_index("ix_system_auth_policies_system_id", table_name="system_auth_policies")
    op.drop_table("system_auth_policies")
