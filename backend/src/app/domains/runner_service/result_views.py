from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ExecutionSummary(BaseModel):
    execution_run_id: UUID
    status: str
    auth_status: str | None = None
    duration_ms: int | None = None
    failure_category: str | None = None
    asset_version: str | None = None
    snapshot_version: str | None = None
    final_url: str | None = None
    page_title: str | None = None


class ArtifactItem(BaseModel):
    id: UUID
    artifact_kind: str
    result_status: str
    artifact_uri: str | None = None
    payload: dict[str, object] | None = None
    created_at: datetime


class CheckResultView(BaseModel):
    request_id: UUID
    plan_id: UUID | None = None
    page_check_id: UUID | None = None
    execution_track: Literal["precompiled", "realtime_probe"] | None = None
    execution_summary: ExecutionSummary | None = None
    artifacts: list[ArtifactItem] = Field(default_factory=list)
    needs_recrawl: bool = False
    needs_recompile: bool = False
