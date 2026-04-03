"""asset reconciliation and retirement lifecycle schema

Revision ID: 0009_asset_recon_retire
Revises: 0008_crawl_failure_metadata
Create Date: 2026-04-03 15:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0009_asset_recon_retire"
down_revision = "0008_crawl_failure_metadata"
branch_labels = None
depends_on = None


asset_status = sa.Enum(
    "safe",
    "suspect",
    "stale",
    name="asset_status",
    native_enum=False,
)

asset_lifecycle_status = sa.Enum(
    "active",
    "retired_missing",
    "retired_replaced",
    "retired_manual",
    name="asset_lifecycle_status",
    native_enum=False,
)

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("page_assets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "drift_status",
                asset_status,
                nullable=False,
                server_default=sa.text("'safe'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "lifecycle_status",
                asset_lifecycle_status,
                nullable=False,
                server_default=sa.text("'active'"),
            )
        )
        batch_op.add_column(sa.Column("retired_reason", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("retired_by_snapshot_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_page_assets_retired_by_snapshot_id_crawl_snapshots",
            "crawl_snapshots",
            ["retired_by_snapshot_id"],
            ["id"],
        )

    page_assets = sa.table(
        "page_assets",
        sa.column("status", sa.String(length=32)),
        sa.column("drift_status", sa.String(length=32)),
    )
    op.execute(sa.update(page_assets).values(drift_status=page_assets.c.status))

    with op.batch_alter_table("page_checks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "lifecycle_status",
                asset_lifecycle_status,
                nullable=False,
                server_default=sa.text("'active'"),
            )
        )
        batch_op.add_column(sa.Column("retired_reason", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("retired_by_snapshot_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("blocking_dependency_json", json_type, nullable=True))
        batch_op.create_foreign_key(
            "fk_page_checks_retired_by_snapshot_id_crawl_snapshots",
            "crawl_snapshots",
            ["retired_by_snapshot_id"],
            ["id"],
        )

    with op.batch_alter_table("intent_aliases") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(sa.Column("disabled_reason", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("disabled_by_snapshot_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_intent_aliases_disabled_by_snapshot_id_crawl_snapshots",
            "crawl_snapshots",
            ["disabled_by_snapshot_id"],
            ["id"],
        )

    with op.batch_alter_table("published_jobs") as batch_op:
        batch_op.add_column(sa.Column("pause_reason", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("paused_by_snapshot_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("paused_by_asset_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("paused_by_page_check_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_published_jobs_paused_by_snapshot_id_crawl_snapshots",
            "crawl_snapshots",
            ["paused_by_snapshot_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_published_jobs_paused_by_asset_id_page_assets",
            "page_assets",
            ["paused_by_asset_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_published_jobs_paused_by_page_check_id_page_checks",
            "page_checks",
            ["paused_by_page_check_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_published_jobs_paused_by_snapshot_id",
            ["paused_by_snapshot_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_published_jobs_paused_by_asset_id",
            ["paused_by_asset_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_published_jobs_paused_by_page_check_id",
            ["paused_by_page_check_id"],
            unique=False,
        )

    op.create_table(
        "asset_reconciliation_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("retired_asset_ids", json_type, nullable=False),
        sa.Column("retired_check_ids", json_type, nullable=False),
        sa.Column("retire_reasons", json_type, nullable=False),
        sa.Column("paused_published_job_ids", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["crawl_snapshots.id"]),
    )
    op.create_index(
        "ix_asset_reconciliation_audits_snapshot_id",
        "asset_reconciliation_audits",
        ["snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_reconciliation_audits_snapshot_id",
        table_name="asset_reconciliation_audits",
    )
    op.drop_table("asset_reconciliation_audits")

    with op.batch_alter_table("published_jobs") as batch_op:
        batch_op.drop_index("ix_published_jobs_paused_by_page_check_id")
        batch_op.drop_index("ix_published_jobs_paused_by_asset_id")
        batch_op.drop_index("ix_published_jobs_paused_by_snapshot_id")
        batch_op.drop_constraint(
            "fk_published_jobs_paused_by_page_check_id_page_checks",
            type_="foreignkey",
        )
        batch_op.drop_constraint("fk_published_jobs_paused_by_asset_id_page_assets", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_published_jobs_paused_by_snapshot_id_crawl_snapshots",
            type_="foreignkey",
        )
        batch_op.drop_column("paused_by_page_check_id")
        batch_op.drop_column("paused_by_asset_id")
        batch_op.drop_column("paused_by_snapshot_id")
        batch_op.drop_column("pause_reason")

    with op.batch_alter_table("intent_aliases") as batch_op:
        batch_op.drop_constraint(
            "fk_intent_aliases_disabled_by_snapshot_id_crawl_snapshots",
            type_="foreignkey",
        )
        batch_op.drop_column("disabled_by_snapshot_id")
        batch_op.drop_column("disabled_at")
        batch_op.drop_column("disabled_reason")
        batch_op.drop_column("is_active")

    with op.batch_alter_table("page_checks") as batch_op:
        batch_op.drop_constraint(
            "fk_page_checks_retired_by_snapshot_id_crawl_snapshots",
            type_="foreignkey",
        )
        batch_op.drop_column("blocking_dependency_json")
        batch_op.drop_column("retired_by_snapshot_id")
        batch_op.drop_column("retired_at")
        batch_op.drop_column("retired_reason")
        batch_op.drop_column("lifecycle_status")

    with op.batch_alter_table("page_assets") as batch_op:
        batch_op.drop_constraint(
            "fk_page_assets_retired_by_snapshot_id_crawl_snapshots",
            type_="foreignkey",
        )
        batch_op.drop_column("retired_by_snapshot_id")
        batch_op.drop_column("retired_at")
        batch_op.drop_column("retired_reason")
        batch_op.drop_column("lifecycle_status")
        batch_op.drop_column("drift_status")
