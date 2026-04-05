"""crawl navigation materialization metadata

Revision ID: 0014_crawl_nav_material
Revises: 0013_merge_0012_heads
Create Date: 2026-04-05 12:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0014_crawl_nav_material"
down_revision = "0013_merge_0012_heads"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch_op:
        batch_op.add_column(sa.Column("navigation_diagnostics", json_type, nullable=True))

    with op.batch_alter_table("page_elements") as batch_op:
        batch_op.add_column(sa.Column("materialized_by", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("navigation_diagnostics", json_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("page_elements") as batch_op:
        batch_op.drop_column("navigation_diagnostics")
        batch_op.drop_column("materialized_by")

    with op.batch_alter_table("pages") as batch_op:
        batch_op.drop_column("navigation_diagnostics")
