"""initial platform schema

Revision ID: 0001_initial_platform_schema
Revises:
Create Date: 2026-04-01 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_platform_schema"
down_revision = None
branch_labels = None
depends_on = None


asset_status = sa.Enum(
    "draft",
    "ready",
    "deprecated",
    name="asset_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "systems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "system_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("credential_key", sa.String(length=128), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("system_id", "credential_key"),
    )
    op.create_index(
        "ix_system_credentials_system_id",
        "system_credentials",
        ["system_id"],
        unique=False,
    )

    op.create_table(
        "auth_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("storage_ref", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_auth_states_system_id", "auth_states", ["system_id"], unique=False)

    op.create_table(
        "crawl_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_ref", sa.Text(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_crawl_snapshots_system_id",
        "crawl_snapshots",
        ["system_id"],
        unique=False,
    )

    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pages_system_id", "pages", ["system_id"], unique=False)

    op.create_table(
        "page_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("asset_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", asset_status, nullable=False, server_default="draft"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_page_assets_page_id", "page_assets", ["page_id"], unique=False)

    op.create_table(
        "page_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_asset_id", sa.Integer(), nullable=False),
        sa.Column("check_key", sa.String(length=128), nullable=False),
        sa.Column("check_spec", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["page_asset_id"], ["page_assets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("page_asset_id", "check_key"),
    )
    op.create_index("ix_page_checks_page_asset_id", "page_checks", ["page_asset_id"], unique=False)

    op.create_table(
        "intent_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_check_id", sa.Integer(), nullable=False),
        sa.Column("intent_key", sa.String(length=128), nullable=False),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["page_check_id"], ["page_checks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("page_check_id", "alias"),
    )
    op.create_index(
        "ix_intent_aliases_page_check_id",
        "intent_aliases",
        ["page_check_id"],
        unique=False,
    )

    op.create_table(
        "execution_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_check_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("runtime_policy", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["page_check_id"], ["page_checks.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_execution_requests_page_check_id",
        "execution_requests",
        ["page_check_id"],
        unique=False,
    )

    op.create_table(
        "execution_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_request_id", sa.Integer(), nullable=False),
        sa.Column("module_plan", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["execution_requests.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_execution_plans_execution_request_id",
        "execution_plans",
        ["execution_request_id"],
        unique=False,
    )

    op.create_table(
        "execution_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_plan_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["execution_plan_id"], ["execution_plans.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_execution_runs_execution_plan_id",
        "execution_runs",
        ["execution_plan_id"],
        unique=False,
    )

    op.create_table(
        "queued_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_request_id", sa.Integer(), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="queued"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["execution_request_id"],
            ["execution_requests.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_queued_jobs_execution_request_id",
        "queued_jobs",
        ["execution_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_queued_jobs_execution_request_id", table_name="queued_jobs")
    op.drop_table("queued_jobs")

    op.drop_index("ix_execution_runs_execution_plan_id", table_name="execution_runs")
    op.drop_table("execution_runs")

    op.drop_index("ix_execution_plans_execution_request_id", table_name="execution_plans")
    op.drop_table("execution_plans")

    op.drop_index("ix_execution_requests_page_check_id", table_name="execution_requests")
    op.drop_table("execution_requests")

    op.drop_index("ix_intent_aliases_page_check_id", table_name="intent_aliases")
    op.drop_table("intent_aliases")

    op.drop_index("ix_page_checks_page_asset_id", table_name="page_checks")
    op.drop_table("page_checks")

    op.drop_index("ix_page_assets_page_id", table_name="page_assets")
    op.drop_table("page_assets")

    op.drop_index("ix_pages_system_id", table_name="pages")
    op.drop_table("pages")

    op.drop_index("ix_crawl_snapshots_system_id", table_name="crawl_snapshots")
    op.drop_table("crawl_snapshots")

    op.drop_index("ix_auth_states_system_id", table_name="auth_states")
    op.drop_table("auth_states")

    op.drop_index("ix_system_credentials_system_id", table_name="system_credentials")
    op.drop_table("system_credentials")

    op.drop_table("systems")
