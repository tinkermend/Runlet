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
    page_summary: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )
    keywords: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    crawled_at: datetime = Field(default_factory=utcnow)


class MenuNode(BaseModel, table=True):
    __tablename__ = "menu_nodes"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    snapshot_id: UUID = Field(foreign_key="crawl_snapshots.id", index=True)
    parent_id: UUID | None = Field(default=None, foreign_key="menu_nodes.id", index=True)
    page_id: UUID | None = Field(default=None, foreign_key="pages.id", index=True)
    label: str = Field(max_length=255)
    route_path: str | None = Field(default=None, max_length=512)
    depth: int = Field(default=0)
    sort_order: int = Field(default=0)
    playwright_locator: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )


class PageElement(BaseModel, table=True):
    __tablename__ = "page_elements"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    snapshot_id: UUID = Field(foreign_key="crawl_snapshots.id", index=True)
    page_id: UUID = Field(foreign_key="pages.id", index=True)
    element_type: str = Field(max_length=64)
    element_role: str | None = Field(default=None, max_length=64)
    element_text: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )
    attributes: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    playwright_locator: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )
    stability_score: float | None = Field(default=None)
    usage_description: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )
