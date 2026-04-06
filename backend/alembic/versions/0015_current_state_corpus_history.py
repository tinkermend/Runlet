"""current-state crawl schema and history corpus baseline

Revision ID: 0015_current_state_hist_corpus
Revises: 0014_crawl_nav_material
Create Date: 2026-04-06 10:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0015_current_state_hist_corpus"
down_revision = "0014_crawl_nav_material"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("crawl_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "state",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'draft'"),
            )
        )
        batch_op.add_column(sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_crawl_snapshots_system_id_active",
        "crawl_snapshots",
        ["system_id"],
        unique=True,
        sqlite_where=sa.text("state = 'active'"),
        postgresql_where=sa.text("state = 'active'"),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE crawl_snapshots
            ALTER COLUMN warning_messages TYPE jsonb
            USING warning_messages::jsonb
            """
        )
        op.execute(
            """
            ALTER TABLE crawl_snapshots
            ALTER COLUMN warning_messages SET DEFAULT '[]'::jsonb
            """
        )

    op.create_table(
        "crawl_snapshots_hist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_type", sa.String(length=32), nullable=False),
        sa.Column("framework_detected", sa.String(length=32), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source_active_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("replaced_by_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("warning_messages", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("structure_hash", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index(
        "ix_crawl_snapshots_hist_snapshot_id",
        "crawl_snapshots_hist",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_snapshots_hist_system_id",
        "crawl_snapshots_hist",
        ["system_id"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_snapshots_hist_source_active_snapshot_id",
        "crawl_snapshots_hist",
        ["source_active_snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_snapshots_hist_replaced_by_snapshot_id",
        "crawl_snapshots_hist",
        ["replaced_by_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "pages_hist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("route_path", sa.String(length=512), nullable=False),
        sa.Column("page_title", sa.String(length=255), nullable=True),
        sa.Column("page_summary", sa.Text(), nullable=True),
        sa.Column("keywords", json_type, nullable=True),
        sa.Column("discovery_sources", json_type, nullable=True),
        sa.Column("entry_candidates", json_type, nullable=True),
        sa.Column("context_constraints", json_type, nullable=True),
        sa.Column("navigation_diagnostics", json_type, nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index("ix_pages_hist_page_id", "pages_hist", ["page_id"], unique=False)
    op.create_index("ix_pages_hist_system_id", "pages_hist", ["system_id"], unique=False)
    op.create_index("ix_pages_hist_snapshot_id", "pages_hist", ["snapshot_id"], unique=False)

    op.create_table(
        "menu_nodes_hist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("menu_node_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("route_path", sa.String(length=512), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("playwright_locator", sa.Text(), nullable=True),
        sa.Column("discovery_sources", json_type, nullable=True),
        sa.Column("entry_candidates", json_type, nullable=True),
        sa.Column("context_constraints", json_type, nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index("ix_menu_nodes_hist_menu_node_id", "menu_nodes_hist", ["menu_node_id"], unique=False)
    op.create_index("ix_menu_nodes_hist_system_id", "menu_nodes_hist", ["system_id"], unique=False)
    op.create_index("ix_menu_nodes_hist_snapshot_id", "menu_nodes_hist", ["snapshot_id"], unique=False)
    op.create_index("ix_menu_nodes_hist_parent_id", "menu_nodes_hist", ["parent_id"], unique=False)
    op.create_index("ix_menu_nodes_hist_page_id", "menu_nodes_hist", ["page_id"], unique=False)

    op.create_table(
        "page_elements_hist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_element_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("element_type", sa.String(length=64), nullable=False),
        sa.Column("element_role", sa.String(length=64), nullable=True),
        sa.Column("element_text", sa.Text(), nullable=True),
        sa.Column("attributes", json_type, nullable=True),
        sa.Column("playwright_locator", sa.Text(), nullable=True),
        sa.Column("state_signature", sa.String(length=255), nullable=True),
        sa.Column("state_context", json_type, nullable=True),
        sa.Column("locator_candidates", json_type, nullable=True),
        sa.Column("materialized_by", sa.Text(), nullable=True),
        sa.Column("navigation_diagnostics", json_type, nullable=True),
        sa.Column("stability_score", sa.Float(), nullable=True),
        sa.Column("usage_description", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
    )
    op.create_index(
        "ix_page_elements_hist_page_element_id",
        "page_elements_hist",
        ["page_element_id"],
        unique=False,
    )
    op.create_index("ix_page_elements_hist_system_id", "page_elements_hist", ["system_id"], unique=False)
    op.create_index("ix_page_elements_hist_snapshot_id", "page_elements_hist", ["snapshot_id"], unique=False)
    op.create_index("ix_page_elements_hist_page_id", "page_elements_hist", ["page_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE crawl_snapshots
            ALTER COLUMN warning_messages TYPE json
            USING warning_messages::json
            """
        )
        op.execute(
            """
            ALTER TABLE crawl_snapshots
            ALTER COLUMN warning_messages SET DEFAULT '[]'::json
            """
        )

    op.drop_index("ix_page_elements_hist_page_id", table_name="page_elements_hist")
    op.drop_index("ix_page_elements_hist_snapshot_id", table_name="page_elements_hist")
    op.drop_index("ix_page_elements_hist_system_id", table_name="page_elements_hist")
    op.drop_index("ix_page_elements_hist_page_element_id", table_name="page_elements_hist")
    op.drop_table("page_elements_hist")

    op.drop_index("ix_menu_nodes_hist_page_id", table_name="menu_nodes_hist")
    op.drop_index("ix_menu_nodes_hist_parent_id", table_name="menu_nodes_hist")
    op.drop_index("ix_menu_nodes_hist_snapshot_id", table_name="menu_nodes_hist")
    op.drop_index("ix_menu_nodes_hist_system_id", table_name="menu_nodes_hist")
    op.drop_index("ix_menu_nodes_hist_menu_node_id", table_name="menu_nodes_hist")
    op.drop_table("menu_nodes_hist")

    op.drop_index("ix_pages_hist_snapshot_id", table_name="pages_hist")
    op.drop_index("ix_pages_hist_system_id", table_name="pages_hist")
    op.drop_index("ix_pages_hist_page_id", table_name="pages_hist")
    op.drop_table("pages_hist")

    op.drop_index("ix_crawl_snapshots_hist_system_id", table_name="crawl_snapshots_hist")
    op.drop_index("ix_crawl_snapshots_hist_snapshot_id", table_name="crawl_snapshots_hist")
    op.drop_index(
        "ix_crawl_snapshots_hist_source_active_snapshot_id",
        table_name="crawl_snapshots_hist",
    )
    op.drop_index(
        "ix_crawl_snapshots_hist_replaced_by_snapshot_id",
        table_name="crawl_snapshots_hist",
    )
    op.drop_table("crawl_snapshots_hist")
    op.drop_index("uq_crawl_snapshots_system_id_active", table_name="crawl_snapshots")

    with op.batch_alter_table("crawl_snapshots") as batch_op:
        batch_op.drop_column("discarded_at")
        batch_op.drop_column("activated_at")
        batch_op.drop_column("state")
