from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel
from app.shared.enums import QueuedJobStatus


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QueuedJob(BaseModel, table=True):
    __tablename__ = "queued_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_type: str = Field(index=True, max_length=64)
    payload: dict[str, object] = Field(sa_column=sa.Column(json_type, nullable=False))
    status: str = Field(default=QueuedJobStatus.ACCEPTED.value, max_length=32)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    failure_message: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )
