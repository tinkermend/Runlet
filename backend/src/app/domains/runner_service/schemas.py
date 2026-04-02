from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


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


class RunPageCheckResult(BaseModel):
    page_check_id: UUID
    execution_run_id: UUID
    status: RunnerRunStatus
    auth_status: AuthInjectStatus
    artifact_ids: list[UUID]
    step_results: list[StepExecutionResult]
