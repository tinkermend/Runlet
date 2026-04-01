from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Enum
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel
from app.shared.enums import AssetStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PageAsset(BaseModel, table=True):
    __tablename__ = "page_assets"

    id: int | None = Field(default=None, primary_key=True)
    page_id: int = Field(foreign_key="pages.id", nullable=False)
    asset_version: int = Field(default=1, nullable=False)
    status: AssetStatus = Field(
        default=AssetStatus.DRAFT,
        sa_column=Column(
            Enum(AssetStatus, name="asset_status", native_enum=False),
            nullable=False,
            default=AssetStatus.DRAFT.value,
        ),
    )
    summary: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class PageCheck(BaseModel, table=True):
    __tablename__ = "page_checks"

    id: int | None = Field(default=None, primary_key=True)
    page_asset_id: int = Field(foreign_key="page_assets.id", nullable=False)
    check_key: str = Field(max_length=128, nullable=False)
    check_spec: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class IntentAlias(BaseModel, table=True):
    __tablename__ = "intent_aliases"

    id: int | None = Field(default=None, primary_key=True)
    page_check_id: int = Field(foreign_key="page_checks.id", nullable=False)
    intent_key: str = Field(max_length=128, nullable=False)
    alias: str = Field(max_length=128, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
