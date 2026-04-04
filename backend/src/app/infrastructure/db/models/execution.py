from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from app.infrastructure.db.base import BaseModel
from app.shared.enums import ExecutionResultStatus, RenderResultStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def execution_result_status_enum() -> sa.Enum:
    return sa.Enum(
        ExecutionResultStatus,
        name="execution_result_status",
        native_enum=False,
        values_callable=lambda values: [value.value for value in values],
    )


def render_result_status_enum() -> sa.Enum:
    return sa.Enum(
        RenderResultStatus,
        name="render_result_status",
        native_enum=False,
        values_callable=lambda values: [value.value for value in values],
    )

json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


class ExecutionRequest(BaseModel, table=True):
    __tablename__ = "execution_requests"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    request_source: str = Field(max_length=32)
    system_hint: str = Field(max_length=255)
    page_hint: str | None = Field(default=None, max_length=255)
    check_goal: str = Field(max_length=64)
    strictness: str = Field(default="balanced", max_length=32)
    time_budget_ms: int = Field(default=20_000)
    template_code: str | None = Field(default=None, max_length=64)
    template_version: str | None = Field(default=None, max_length=32)
    carrier_hint: str | None = Field(default=None, max_length=16)
    template_params: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )

    plans: list["ExecutionPlan"] = Relationship(
        back_populates="request",
        sa_relationship=relationship("ExecutionPlan", back_populates="request"),
    )


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

    request: "ExecutionRequest | None" = Relationship(
        back_populates="plans",
        sa_relationship=relationship("ExecutionRequest", back_populates="plans"),
    )
    runs: list["ExecutionRun"] = Relationship(
        back_populates="plan",
        sa_relationship=relationship("ExecutionRun", back_populates="plan"),
    )


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
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )

    plan: "ExecutionPlan | None" = Relationship(
        back_populates="runs",
        sa_relationship=relationship("ExecutionPlan", back_populates="runs"),
    )
    artifacts: list["ExecutionArtifact"] = Relationship(
        back_populates="run",
        sa_relationship=relationship("ExecutionArtifact", back_populates="run"),
    )


class ExecutionArtifact(BaseModel, table=True):
    __tablename__ = "execution_artifacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_run_id: UUID = Field(foreign_key="execution_runs.id", index=True)
    artifact_kind: str = Field(max_length=64)
    result_status: ExecutionResultStatus = Field(
        default=ExecutionResultStatus.PENDING,
        sa_column=sa.Column(execution_result_status_enum(), nullable=False),
    )
    payload: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    artifact_uri: str | None = Field(default=None, max_length=1024)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )

    run: "ExecutionRun | None" = Relationship(
        back_populates="artifacts",
        sa_relationship=relationship("ExecutionRun", back_populates="artifacts"),
    )


class ScriptRender(BaseModel, table=True):
    __tablename__ = "script_renders"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    execution_artifact_id: UUID | None = Field(
        default=None,
        foreign_key="execution_artifacts.id",
        index=True,
    )
    execution_plan_id: UUID | None = Field(default=None, foreign_key="execution_plans.id", index=True)
    render_mode: str = Field(max_length=32)
    render_result: RenderResultStatus = Field(
        default=RenderResultStatus.PENDING,
        sa_column=sa.Column(render_result_status_enum(), nullable=False),
    )
    script_body: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.Text(), nullable=True),
    )
    render_metadata: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
