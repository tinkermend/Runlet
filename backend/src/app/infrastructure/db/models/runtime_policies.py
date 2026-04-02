from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel
from app.shared.enums import CrawlScope, RuntimePolicyState


class SystemAuthPolicy(BaseModel, table=True):
    __tablename__ = "system_auth_policies"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True, unique=True)
    enabled: bool = Field(default=True)
    state: str = Field(default=RuntimePolicyState.ACTIVE.value, max_length=32)
    schedule_expr: str = Field(max_length=255)
    auth_mode: str = Field(max_length=32)
    captcha_provider: str = Field(default="ddddocr", max_length=64)
    last_triggered_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )


class SystemCrawlPolicy(BaseModel, table=True):
    __tablename__ = "system_crawl_policies"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True, unique=True)
    enabled: bool = Field(default=True)
    state: str = Field(default=RuntimePolicyState.ACTIVE.value, max_length=32)
    schedule_expr: str = Field(max_length=255)
    crawl_scope: str = Field(default=CrawlScope.FULL.value, max_length=32)
    last_triggered_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
