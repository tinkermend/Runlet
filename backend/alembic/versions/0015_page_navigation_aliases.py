"""add page navigation aliases

Revision ID: 0015_page_navigation_aliases
Revises: 0014_crawl_nav_material
Create Date: 2026-04-06 10:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_page_navigation_aliases"
down_revision = "0014_crawl_nav_material"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_navigation_aliases",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("page_asset_id", sa.Uuid(), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("alias_text", sa.String(length=512), nullable=False),
        sa.Column("leaf_text", sa.String(length=255), nullable=True),
        sa.Column("display_chain", sa.String(length=1024), nullable=True),
        sa.Column("chain_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disabled_reason", sa.String(length=64), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by_snapshot_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["page_asset_id"], ["page_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disabled_by_snapshot_id"], ["crawl_snapshots.id"]),
    )
    op.create_index(
        "ix_page_navigation_aliases_system_id",
        "page_navigation_aliases",
        ["system_id"],
        unique=False,
    )
    op.create_index(
        "ix_page_navigation_aliases_page_asset_id",
        "page_navigation_aliases",
        ["page_asset_id"],
        unique=False,
    )
    op.create_index(
        "ix_page_navigation_aliases_alias_type",
        "page_navigation_aliases",
        ["alias_type"],
        unique=False,
    )
    op.create_index(
        "ix_page_navigation_aliases_alias_text",
        "page_navigation_aliases",
        ["alias_text"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_page_navigation_aliases_alias_text", table_name="page_navigation_aliases")
    op.drop_index("ix_page_navigation_aliases_alias_type", table_name="page_navigation_aliases")
    op.drop_index("ix_page_navigation_aliases_page_asset_id", table_name="page_navigation_aliases")
    op.drop_index("ix_page_navigation_aliases_system_id", table_name="page_navigation_aliases")
    op.drop_table("page_navigation_aliases")
