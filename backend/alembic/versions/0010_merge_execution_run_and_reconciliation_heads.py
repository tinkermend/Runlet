"""merge execution run timestamp and asset reconciliation heads

Revision ID: 0010_merge_exec_run_recon
Revises: 0009_execution_run_created_at, 0009_asset_recon_retire
Create Date: 2026-04-03 18:45:00.000000
"""

from __future__ import annotations


revision = "0010_merge_exec_run_recon"
down_revision = ("0009_execution_run_created_at", "0009_asset_recon_retire")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
