"""crawl state and locator evidence columns

Revision ID: 0011_crawl_state_loc_evid
Revises: 0010_merge_exec_run_recon
Create Date: 2026-04-03 21:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0011_crawl_state_loc_evid"
down_revision = "0010_merge_exec_run_recon"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch_op:
        batch_op.add_column(sa.Column("discovery_sources", json_type, nullable=True))
        batch_op.add_column(sa.Column("entry_candidates", json_type, nullable=True))
        batch_op.add_column(sa.Column("context_constraints", json_type, nullable=True))

    with op.batch_alter_table("menu_nodes") as batch_op:
        batch_op.add_column(sa.Column("discovery_sources", json_type, nullable=True))
        batch_op.add_column(sa.Column("entry_candidates", json_type, nullable=True))
        batch_op.add_column(sa.Column("context_constraints", json_type, nullable=True))

    with op.batch_alter_table("page_elements") as batch_op:
        batch_op.add_column(sa.Column("state_signature", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("state_context", json_type, nullable=True))
        batch_op.add_column(sa.Column("locator_candidates", json_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("page_elements") as batch_op:
        batch_op.drop_column("locator_candidates")
        batch_op.drop_column("state_context")
        batch_op.drop_column("state_signature")

    with op.batch_alter_table("menu_nodes") as batch_op:
        batch_op.drop_column("context_constraints")
        batch_op.drop_column("entry_candidates")
        batch_op.drop_column("discovery_sources")

    with op.batch_alter_table("pages") as batch_op:
        batch_op.drop_column("context_constraints")
        batch_op.drop_column("entry_candidates")
        batch_op.drop_column("discovery_sources")
