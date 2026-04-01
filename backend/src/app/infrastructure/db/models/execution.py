from __future__ import annotations

from uuid import UUID, uuid4

from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


class ExecutionRequest(BaseModel, table=True):
    __tablename__ = "execution_requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    request_source: str = Field(max_length=32)
    system_hint: str = Field(max_length=255)
    page_hint: str | None = Field(default=None, max_length=255)
    check_goal: str = Field(max_length=64)
    strictness: str = Field(default="balanced", max_length=32)
    time_budget_ms: int = Field(default=20_000)


class ExecutionPlan(BaseModel, table=True):
    __tablename__ = "execution_plans"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_request_id: UUID = Field(foreign_key="execution_requests.id", index=True)
    resolved_system_id: UUID | None = Field(default=None, foreign_key="systems.id", index=True)
    resolved_page_asset_id: UUID | None = Field(default=None, foreign_key="page_assets.id", index=True)
    resolved_page_check_id: UUID | None = Field(default=None, foreign_key="page_checks.id", index=True)
    execution_track: str = Field(max_length=32)
    auth_policy: str = Field(max_length=64)
    module_plan_id: UUID | None = Field(default=None)


class ExecutionRun(BaseModel, table=True):
    __tablename__ = "execution_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_plan_id: UUID = Field(foreign_key="execution_plans.id", index=True)
    status: str = Field(max_length=32)
    duration_ms: int | None = Field(default=None)
    auth_status: str | None = Field(default=None, max_length=32)
    failure_category: str | None = Field(default=None, max_length=64)
    asset_version: str | None = Field(default=None, max_length=64)
    snapshot_version: str | None = Field(default=None, max_length=64)
