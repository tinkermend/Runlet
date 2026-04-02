"""asset compiler and drift schema

Revision ID: 0003_asset_compiler_and_drift
Revises: 0002_auth_and_crawl_runtime
Create Date: 2026-04-02 10:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_asset_compiler_and_drift"
down_revision = "0002_auth_and_crawl_runtime"
branch_labels = None
depends_on = None


asset_status = sa.Enum(
    "safe",
    "suspect",
    "stale",
    name="asset_status",
    native_enum=False,
)

legacy_asset_status = sa.Enum(
    "draft",
    "ready",
    "suspect",
    "stale",
    "disabled",
    name="asset_status",
    native_enum=False,
)

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    page_assets = sa.table("page_assets", sa.column("status", sa.String(length=32)))
    op.execute(
        sa.update(page_assets).values(
            status=sa.case(
                (page_assets.c.status == sa.literal("stale"), sa.literal("stale")),
                (page_assets.c.status == sa.literal("suspect"), sa.literal("suspect")),
                else_=sa.literal("safe"),
            )
        )
    )
    with op.batch_alter_table("page_assets") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=legacy_asset_status,
            type_=asset_status,
            existing_nullable=False,
        )
    with op.batch_alter_table("queued_jobs") as batch_op:
        batch_op.add_column(sa.Column("result_payload", json_type, nullable=True))

    op.create_table(
        "module_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_asset_id", sa.Uuid(), nullable=False),
        sa.Column("check_code", sa.String(length=64), nullable=False),
        sa.Column("plan_version", sa.String(length=32), nullable=False),
        sa.Column("steps_json", json_type, nullable=False),
        sa.ForeignKeyConstraint(["page_asset_id"], ["page_assets.id"]),
    )
    op.create_index("ix_module_plans_page_asset_id", "module_plans", ["page_asset_id"], unique=False)
    op.create_index("ix_module_plans_check_code", "module_plans", ["check_code"], unique=False)

    op.create_table(
        "asset_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_asset_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version", sa.String(length=64), nullable=False),
        sa.Column("structure_hash", sa.String(length=64), nullable=False),
        sa.Column("navigation_hash", sa.String(length=64), nullable=False),
        sa.Column("key_locator_hash", sa.String(length=64), nullable=False),
        sa.Column("semantic_summary_hash", sa.String(length=64), nullable=False),
        sa.Column("diff_score_vs_previous", sa.Float(), nullable=False),
        sa.Column("status", asset_status, nullable=False),
        sa.ForeignKeyConstraint(["page_asset_id"], ["page_assets.id"]),
        sa.ForeignKeyConstraint(["crawl_snapshot_id"], ["crawl_snapshots.id"]),
    )
    op.create_index("ix_asset_snapshots_page_asset_id", "asset_snapshots", ["page_asset_id"], unique=False)
    op.create_index(
        "ix_asset_snapshots_crawl_snapshot_id",
        "asset_snapshots",
        ["crawl_snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_asset_snapshots_crawl_snapshot_id", table_name="asset_snapshots")
    op.drop_index("ix_asset_snapshots_page_asset_id", table_name="asset_snapshots")
    op.drop_table("asset_snapshots")

    op.drop_index("ix_module_plans_check_code", table_name="module_plans")
    op.drop_index("ix_module_plans_page_asset_id", table_name="module_plans")
    op.drop_table("module_plans")

    with op.batch_alter_table("queued_jobs") as batch_op:
        batch_op.drop_column("result_payload")

    page_assets = sa.table("page_assets", sa.column("status", sa.String(length=32)))
    op.execute(
        sa.update(page_assets).values(
            status=sa.case(
                (page_assets.c.status == sa.literal("stale"), sa.literal("stale")),
                (page_assets.c.status == sa.literal("suspect"), sa.literal("suspect")),
                else_=sa.literal("ready"),
            )
        )
    )
    with op.batch_alter_table("page_assets") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=asset_status,
            type_=legacy_asset_status,
            existing_nullable=False,
        )
