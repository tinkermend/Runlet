from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel
from app.shared.enums import PublishedJobState, QueuedJobStatus


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def published_job_state_enum() -> sa.Enum:
    return sa.Enum(
        PublishedJobState,
        name="published_job_state",
        native_enum=False,
        values_callable=lambda values: [value.value for value in values],
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QueuedJob(BaseModel, table=True):
    __tablename__ = "queued_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_type: str = Field(index=True, max_length=64)
    payload: dict[str, object] = Field(sa_column=sa.Column(json_type, nullable=False))
    result_payload: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
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


class PublishedJob(BaseModel, table=True):
    __tablename__ = "published_jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_key: str = Field(
        sa_column=sa.Column(
            sa.String(length=128),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    page_check_id: UUID = Field(foreign_key="page_checks.id", index=True)
    script_render_id: UUID | None = Field(default=None, foreign_key="script_renders.id", index=True)
    asset_version: str | None = Field(default=None, max_length=64)
    runtime_policy: str = Field(default="default", max_length=64)
    schedule_expr: str = Field(max_length=255)
    timezone: str = Field(default="UTC", max_length=64)
    state: PublishedJobState = Field(
        default=PublishedJobState.ACTIVE,
        sa_column=sa.Column(published_job_state_enum(), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False, onupdate=utcnow),
    )


class JobRun(BaseModel, table=True):
    __tablename__ = "job_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    published_job_id: UUID = Field(foreign_key="published_jobs.id", index=True)
    queued_job_id: UUID | None = Field(default=None, foreign_key="queued_jobs.id", index=True)
    execution_run_id: UUID | None = Field(default=None, foreign_key="execution_runs.id", index=True)
    # Snapshot fields for auditability. PublishedJob may change after a run is created.
    script_render_id: UUID | None = Field(default=None, foreign_key="script_renders.id", index=True)
    asset_version: str | None = Field(default=None, max_length=64)
    runtime_policy: str = Field(
        default="default",
        sa_column=sa.Column(sa.String(length=64), nullable=False, server_default="default"),
    )
    schedule_expr: str | None = Field(default=None, max_length=255)
    trigger_source: str = Field(default="scheduler", max_length=32)
    run_status: str = Field(default=QueuedJobStatus.ACCEPTED.value, max_length=32)
    scheduled_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
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
