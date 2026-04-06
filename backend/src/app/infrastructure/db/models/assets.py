from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import field_validator
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

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


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


class UUIDSafeJSONType(sa.TypeDecorator):
    impl = sa.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB(astext_type=sa.Text()))
        return dialect.type_descriptor(sa.JSON())

    def process_bind_param(self, value: Any, dialect) -> Any:
        return _json_safe(value)


json_type = UUIDSafeJSONType()


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
    retired_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    retired_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")
    compiled_from_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")
    last_verified_at: datetime | None = Field(default=None)

    checks: list["PageCheck"] = Relationship(
        back_populates="page_asset",
        sa_relationship=relationship(
            "PageCheck",
            back_populates="page_asset",
            cascade="all, delete-orphan",
        ),
    )
    module_plans: list["ModulePlan"] = Relationship(
        back_populates="page_asset",
        sa_relationship=relationship(
            "ModulePlan",
            back_populates="page_asset",
            cascade="all, delete-orphan",
        ),
    )
    asset_snapshots: list["AssetSnapshot"] = Relationship(
        back_populates="page_asset",
        sa_relationship=relationship(
            "AssetSnapshot",
            back_populates="page_asset",
            cascade="all, delete-orphan",
        ),
    )
    navigation_aliases: list["PageNavigationAlias"] = Relationship(
        back_populates="page_asset",
        sa_relationship=relationship(
            "PageNavigationAlias",
            back_populates="page_asset",
            cascade="all, delete-orphan",
        ),
    )


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
    retired_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
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

    page_asset: "PageAsset | None" = Relationship(
        back_populates="checks",
        sa_relationship=relationship("PageAsset", back_populates="checks"),
    )


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
    disabled_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    disabled_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")


class PageNavigationAlias(BaseModel, table=True):
    __tablename__ = "page_navigation_aliases"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    page_asset_id: UUID = Field(
        sa_column=sa.Column(
            sa.Uuid(),
            sa.ForeignKey("page_assets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    alias_type: str = Field(max_length=32, index=True)
    alias_text: str = Field(max_length=512, index=True)
    leaf_text: str | None = Field(default=None, max_length=255)
    display_chain: str | None = Field(default=None, max_length=1024)
    chain_complete: bool = Field(
        default=False,
        sa_column=sa.Column(sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    source: str = Field(max_length=64)
    is_active: bool = Field(
        default=True,
        sa_column=sa.Column(sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    disabled_reason: str | None = Field(default=None, max_length=64)
    disabled_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    disabled_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")

    page_asset: "PageAsset | None" = Relationship(
        back_populates="navigation_aliases",
        sa_relationship=relationship("PageAsset", back_populates="navigation_aliases"),
    )


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

    page_asset: "PageAsset | None" = Relationship(
        back_populates="module_plans",
        sa_relationship=relationship("PageAsset", back_populates="module_plans"),
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

    page_asset: "PageAsset | None" = Relationship(
        back_populates="asset_snapshots",
        sa_relationship=relationship("PageAsset", back_populates="asset_snapshots"),
    )


class AssetReconciliationAudit(BaseModel, table=True):
    __tablename__ = "asset_reconciliation_audits"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    snapshot_id: UUID = Field(foreign_key="crawl_snapshots.id", index=True)
    retired_asset_ids: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    retired_check_ids: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    disabled_alias_ids: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    enabled_alias_ids: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    retire_reasons: list[dict[str, object]] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    paused_published_job_ids: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    resumed_published_job_ids: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(json_type, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )

    @field_validator(
        "retired_asset_ids",
        "retired_check_ids",
        "disabled_alias_ids",
        "enabled_alias_ids",
        "paused_published_job_ids",
        "resumed_published_job_ids",
        mode="before",
    )
    @classmethod
    def _normalize_uuid_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("expected list for identifier audit fields")
        return [str(item) for item in value]
