from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionRequest(BaseModel, table=True):
    __tablename__ = "execution_requests"

    id: int | None = Field(default=None, primary_key=True)
    page_check_id: int = Field(foreign_key="page_checks.id", nullable=False)
    requested_by: str | None = Field(default=None, max_length=128)
    runtime_policy: str | None = Field(default=None)
    status: str = Field(default="pending", max_length=64, nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class ExecutionPlan(BaseModel, table=True):
    __tablename__ = "execution_plans"

    id: int | None = Field(default=None, primary_key=True)
    execution_request_id: int = Field(foreign_key="execution_requests.id", nullable=False)
    module_plan: str = Field(nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class ExecutionRun(BaseModel, table=True):
    __tablename__ = "execution_runs"

    id: int | None = Field(default=None, primary_key=True)
    execution_plan_id: int = Field(foreign_key="execution_plans.id", nullable=False)
    status: str = Field(default="queued", max_length=64, nullable=False)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
