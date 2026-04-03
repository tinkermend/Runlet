from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from app.domains.runner_service.failure_categories import FailureCategory


class RunnerRunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class AuthInjectStatus(StrEnum):
    REUSED = "reused"
    REFRESHED = "refreshed"
    BLOCKED = "blocked"


class StepExecutionResult(BaseModel):
    module: str
    status: RunnerRunStatus
    detail: str | None = None
    output: dict[str, object] | None = None


class ModuleExecutionResult(BaseModel):
    status: RunnerRunStatus
    auth_status: AuthInjectStatus
    step_results: list[StepExecutionResult]


class PageProbePlan(BaseModel):
    route_path: str
    steps_json: list[dict[str, object]]


class RunPageCheckResult(BaseModel):
    page_check_id: UUID | None = None
    execution_run_id: UUID
    status: RunnerRunStatus
    auth_status: AuthInjectStatus
    artifact_ids: list[UUID]
    screenshot_artifact_ids: list[UUID]
    step_results: list[StepExecutionResult]
    failure_category: FailureCategory | None = None
    final_url: str | None = None
    page_title: str | None = None
