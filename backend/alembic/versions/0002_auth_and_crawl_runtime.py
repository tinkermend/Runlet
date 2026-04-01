"""auth and crawl runtime schema

Revision ID: 0002_auth_and_crawl_runtime
Revises: 0001_initial_platform_schema
Create Date: 2026-04-01 22:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_auth_and_crawl_runtime"
down_revision = "0001_initial_platform_schema"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("auth_states") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending")
        )

    # Backfill status for previously-validated auth states.
    # Keep "pending" for rows that were never validated.
    auth_states = sa.table(
        "auth_states",
        sa.column("status", sa.String(length=32)),
        sa.column("validated_at", sa.DateTime(timezone=True)),
        sa.column("expires_at", sa.DateTime(timezone=True)),
        sa.column("is_valid", sa.Boolean()),
    )
    now = sa.func.current_timestamp()
    op.execute(
        sa.update(auth_states).values(
            status=sa.case(
                (auth_states.c.validated_at.is_(None), sa.literal("pending")),
                (
                    sa.and_(
                        auth_states.c.is_valid.is_(True),
                        sa.or_(
                            auth_states.c.expires_at.is_(None),
                            auth_states.c.expires_at > now,
                        ),
                    ),
                    sa.literal("valid"),
                ),
                (
                    sa.and_(
                        auth_states.c.expires_at.is_not(None),
                        auth_states.c.expires_at <= now,
                    ),
                    sa.literal("expired"),
                ),
                else_=sa.literal("invalid"),
            )
        )
    )

    op.create_table(
        "menu_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("route_path", sa.String(length=512), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("playwright_locator", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["crawl_snapshots.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["menu_nodes.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"]),
    )
    op.create_index("ix_menu_nodes_system_id", "menu_nodes", ["system_id"], unique=False)
    op.create_index("ix_menu_nodes_snapshot_id", "menu_nodes", ["snapshot_id"], unique=False)
    op.create_index("ix_menu_nodes_parent_id", "menu_nodes", ["parent_id"], unique=False)
    op.create_index("ix_menu_nodes_page_id", "menu_nodes", ["page_id"], unique=False)

    op.create_table(
        "page_elements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("element_type", sa.String(length=64), nullable=False),
        sa.Column("element_role", sa.String(length=64), nullable=True),
        sa.Column("element_text", sa.Text(), nullable=True),
        sa.Column("attributes", json_type, nullable=True),
        sa.Column("playwright_locator", sa.Text(), nullable=True),
        sa.Column("stability_score", sa.Float(), nullable=True),
        sa.Column("usage_description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["crawl_snapshots.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"]),
    )
    op.create_index("ix_page_elements_system_id", "page_elements", ["system_id"], unique=False)
    op.create_index("ix_page_elements_snapshot_id", "page_elements", ["snapshot_id"], unique=False)
    op.create_index("ix_page_elements_page_id", "page_elements", ["page_id"], unique=False)

    with op.batch_alter_table("queued_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("failure_message", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("queued_jobs") as batch_op:
        batch_op.drop_column("failure_message")
        batch_op.drop_column("finished_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("created_at")

    op.drop_index("ix_page_elements_page_id", table_name="page_elements")
    op.drop_index("ix_page_elements_snapshot_id", table_name="page_elements")
    op.drop_index("ix_page_elements_system_id", table_name="page_elements")
    op.drop_table("page_elements")

    op.drop_index("ix_menu_nodes_page_id", table_name="menu_nodes")
    op.drop_index("ix_menu_nodes_parent_id", table_name="menu_nodes")
    op.drop_index("ix_menu_nodes_snapshot_id", table_name="menu_nodes")
    op.drop_index("ix_menu_nodes_system_id", table_name="menu_nodes")
    op.drop_table("menu_nodes")

    with op.batch_alter_table("auth_states") as batch_op:
        batch_op.drop_column("status")
