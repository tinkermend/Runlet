from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel
from app.shared.enums import AssetLifecycleStatus, AssetStatus


def asset_status_enum() -> sa.Enum:
    return sa.Enum(
        AssetStatus,
        name="asset_status",
        native_enum=False,
        values_callable=lambda values: [value.value for value in values],
    )


def asset_lifecycle_status_enum() -> sa.Enum:
    return sa.Enum(
        AssetLifecycleStatus,
        name="asset_lifecycle_status",
        native_enum=False,
        values_callable=lambda values: [value.value for value in values],
    )


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PageAsset(BaseModel, table=True):
    __tablename__ = "page_assets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    page_id: UUID = Field(foreign_key="pages.id", index=True)
    asset_key: str = Field(index=True, max_length=255)
    asset_version: str = Field(max_length=64)
    status: AssetStatus = Field(
        default=AssetStatus.SAFE,
        sa_column=sa.Column(asset_status_enum(), nullable=False),
    )
    drift_status: AssetStatus = Field(
        default=AssetStatus.SAFE,
        sa_column=sa.Column(asset_status_enum(), nullable=False, server_default=AssetStatus.SAFE.value),
    )
    lifecycle_status: AssetLifecycleStatus = Field(
        default=AssetLifecycleStatus.ACTIVE,
        sa_column=sa.Column(
            asset_lifecycle_status_enum(),
            nullable=False,
            server_default=AssetLifecycleStatus.ACTIVE.value,
        ),
    )
    retired_reason: str | None = Field(default=None, max_length=64)
    retired_at: datetime | None = Field(default=None)
    retired_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")
    compiled_from_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")
    last_verified_at: datetime | None = Field(default=None)


class PageCheck(BaseModel, table=True):
    __tablename__ = "page_checks"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    page_asset_id: UUID = Field(foreign_key="page_assets.id", index=True)
    check_code: str = Field(max_length=64)
    goal: str = Field(max_length=64)
    lifecycle_status: AssetLifecycleStatus = Field(
        default=AssetLifecycleStatus.ACTIVE,
        sa_column=sa.Column(
            asset_lifecycle_status_enum(),
            nullable=False,
            server_default=AssetLifecycleStatus.ACTIVE.value,
        ),
    )
    retired_reason: str | None = Field(default=None, max_length=64)
    retired_at: datetime | None = Field(default=None)
    retired_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")
    input_schema: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    assertion_schema: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    module_plan_id: UUID | None = Field(default=None)
    blocking_dependency_json: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    success_rate: float | None = Field(default=None)
    last_verified_at: datetime | None = Field(default=None)


class IntentAlias(BaseModel, table=True):
    __tablename__ = "intent_aliases"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_alias: str = Field(max_length=255)
    page_alias: str | None = Field(default=None, max_length=255)
    check_alias: str = Field(max_length=64)
    route_hint: str | None = Field(default=None, max_length=512)
    asset_key: str = Field(max_length=255)
    confidence: float = Field(default=1.0)
    source: str = Field(max_length=64)
    is_active: bool = Field(
        default=True,
        sa_column=sa.Column(sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    disabled_reason: str | None = Field(default=None, max_length=64)
    disabled_at: datetime | None = Field(default=None)
    disabled_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")


class ModulePlan(BaseModel, table=True):
    __tablename__ = "module_plans"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    page_asset_id: UUID = Field(foreign_key="page_assets.id", index=True)
    check_code: str = Field(max_length=64, index=True)
    plan_version: str = Field(default="v1", max_length=32)
    steps_json: list[dict[str, object]] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )


class AssetSnapshot(BaseModel, table=True):
    __tablename__ = "asset_snapshots"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    page_asset_id: UUID = Field(foreign_key="page_assets.id", index=True)
    crawl_snapshot_id: UUID = Field(foreign_key="crawl_snapshots.id", index=True)
    asset_version: str = Field(max_length=64)
    structure_hash: str = Field(max_length=64)
    navigation_hash: str = Field(max_length=64)
    key_locator_hash: str = Field(max_length=64)
    semantic_summary_hash: str = Field(max_length=64)
    diff_score_vs_previous: float = Field(default=0.0)
    status: AssetStatus = Field(
        default=AssetStatus.SAFE,
        sa_column=sa.Column(asset_status_enum(), nullable=False),
    )


class AssetReconciliationAudit(BaseModel, table=True):
    __tablename__ = "asset_reconciliation_audits"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    snapshot_id: UUID = Field(foreign_key="crawl_snapshots.id", index=True)
    retired_asset_ids: list[UUID] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    retired_check_ids: list[UUID] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    retire_reasons: list[dict[str, object]] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    paused_published_job_ids: list[UUID] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
