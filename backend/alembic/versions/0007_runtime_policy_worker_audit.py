"""runtime policy worker audit fields

Revision ID: 0007_policy_worker_audit
Revises: 0006_runtime_policies_sched
Create Date: 2026-04-03 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_policy_worker_audit"
down_revision = "0006_runtime_policies_sched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("system_auth_policies") as batch_op:
        batch_op.add_column(sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_failure_message", sa.Text(), nullable=True))

    with op.batch_alter_table("system_crawl_policies") as batch_op:
        batch_op.add_column(sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_failure_message", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("system_crawl_policies") as batch_op:
        batch_op.drop_column("last_failure_message")
        batch_op.drop_column("last_failed_at")
        batch_op.drop_column("last_succeeded_at")

    with op.batch_alter_table("system_auth_policies") as batch_op:
        batch_op.drop_column("last_failure_message")
        batch_op.drop_column("last_failed_at")
        batch_op.drop_column("last_succeeded_at")
