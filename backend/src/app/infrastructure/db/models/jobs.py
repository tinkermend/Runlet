from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


class QueuedJob(BaseModel, table=True):
    __tablename__ = "queued_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_type: str = Field(index=True, max_length=64)
    payload: dict[str, object] = Field(sa_column=sa.Column(json_type, nullable=False))
    status: str = Field(default="accepted", max_length=32)
