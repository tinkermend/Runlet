from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


class CrawlSnapshot(BaseModel, table=True):
    __tablename__ = "crawl_snapshots"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    crawl_type: str = Field(max_length=32)
    framework_detected: str | None = Field(default=None, max_length=32)
    quality_score: float | None = Field(default=None)
    degraded: bool = Field(default=False)
    structure_hash: str | None = Field(default=None, max_length=255)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class Page(BaseModel, table=True):
    __tablename__ = "pages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id", index=True)
    route_path: str = Field(max_length=512)
    page_title: str | None = Field(default=None, max_length=255)
    page_summary: str | None = Field(default=None)
    keywords: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    crawled_at: datetime = Field(default_factory=utcnow)
