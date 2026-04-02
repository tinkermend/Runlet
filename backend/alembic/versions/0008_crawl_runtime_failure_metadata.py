"""crawl runtime failure metadata

Revision ID: 0008_crawl_failure_metadata
Revises: 0007_policy_worker_audit
Create Date: 2026-04-03 11:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_crawl_failure_metadata"
down_revision = "0007_policy_worker_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("crawl_snapshots") as batch_op:
        batch_op.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "warning_messages",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("crawl_snapshots") as batch_op:
        batch_op.drop_column("warning_messages")
        batch_op.drop_column("failure_reason")
