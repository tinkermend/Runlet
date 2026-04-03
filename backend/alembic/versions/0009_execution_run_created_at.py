"""add created_at to execution runs

Revision ID: 0009_execution_run_created_at
Revises: 0008_crawl_failure_metadata
Create Date: 2026-04-03 12:55:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_execution_run_created_at"
down_revision = "0008_crawl_failure_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("execution_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    op.execute(
        """
        UPDATE execution_runs
        SET created_at = COALESCE(
            (
                SELECT MIN(execution_artifacts.created_at)
                FROM execution_artifacts
                WHERE execution_artifacts.execution_run_id = execution_runs.id
            ),
            CURRENT_TIMESTAMP
        )
        """
    )

    with op.batch_alter_table("execution_runs") as batch_op:
        batch_op.alter_column("created_at", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("execution_runs") as batch_op:
        batch_op.drop_column("created_at")
