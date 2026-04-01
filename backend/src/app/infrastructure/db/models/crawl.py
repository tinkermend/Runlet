from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CrawlSnapshot(BaseModel, table=True):
    __tablename__ = "crawl_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="systems.id", nullable=False)
    snapshot_hash: str = Field(max_length=64, nullable=False)
    payload_ref: str | None = Field(default=None)
    captured_at: datetime = Field(default_factory=utcnow, nullable=False)


class Page(BaseModel, table=True):
    __tablename__ = "pages"

    id: int | None = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="systems.id", nullable=False)
    url: str = Field(nullable=False)
    title: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
