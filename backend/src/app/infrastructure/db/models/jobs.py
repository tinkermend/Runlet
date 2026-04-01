from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QueuedJob(BaseModel, table=True):
    __tablename__ = "queued_jobs"

    id: int | None = Field(default=None, primary_key=True)
    execution_request_id: int = Field(foreign_key="execution_requests.id", nullable=False)
    queue_name: str = Field(default="default", max_length=64, nullable=False)
    status: str = Field(default="queued", max_length=64, nullable=False)
    available_at: datetime = Field(default_factory=utcnow, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
