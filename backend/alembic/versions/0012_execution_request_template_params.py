"""persist template metadata columns on execution_requests

Revision ID: 0012_execution_request_template_params
Revises: 0011_crawl_state_loc_evid
Create Date: 2026-04-04 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_execution_request_template_params"
down_revision = "0011_crawl_state_loc_evid"
branch_labels = None
depends_on = None

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("execution_requests") as batch_op:
        batch_op.add_column(sa.Column("template_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("template_version", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("carrier_hint", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("template_params", json_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("execution_requests") as batch_op:
        batch_op.drop_column("template_params")
        batch_op.drop_column("carrier_hint")
        batch_op.drop_column("template_version")
        batch_op.drop_column("template_code")
