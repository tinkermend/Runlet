"""job run audit linkage

Revision ID: 0005_job_run_audit_linkage
Revises: 0004_runner_and_scheduling
Create Date: 2026-04-02 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_job_run_audit_linkage"
down_revision = "0004_runner_and_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch mode so SQLite can handle FK additions (copy-and-move).
    with op.batch_alter_table("job_runs") as batch_op:
        batch_op.add_column(sa.Column("queued_job_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("script_render_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("asset_version", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "runtime_policy",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            )
        )
        batch_op.add_column(sa.Column("schedule_expr", sa.String(length=255), nullable=True))

        batch_op.create_foreign_key(
            "fk_job_runs_queued_job_id",
            "queued_jobs",
            ["queued_job_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_job_runs_script_render_id",
            "script_renders",
            ["script_render_id"],
            ["id"],
        )

        batch_op.create_index("ix_job_runs_queued_job_id", ["queued_job_id"], unique=False)
        batch_op.create_index("ix_job_runs_script_render_id", ["script_render_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job_runs") as batch_op:
        batch_op.drop_index("ix_job_runs_script_render_id")
        batch_op.drop_index("ix_job_runs_queued_job_id")

        batch_op.drop_constraint("fk_job_runs_script_render_id", type_="foreignkey")
        batch_op.drop_constraint("fk_job_runs_queued_job_id", type_="foreignkey")

        batch_op.drop_column("schedule_expr")
        batch_op.drop_column("runtime_policy")
        batch_op.drop_column("asset_version")
        batch_op.drop_column("script_render_id")
        batch_op.drop_column("queued_job_id")
