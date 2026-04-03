from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.shared.enums import AssetStatus


@dataclass(frozen=True)
class StandardCheckDefinition:
    check_code: str
    goal: str
    input_schema: dict[str, object] | None = None
    assertion_schema: dict[str, object] | None = None


@dataclass(frozen=True)
class ModulePlanDraft:
    check_code: str
    plan_version: str
    steps_json: list[dict[str, object]]


@dataclass(frozen=True)
class CompileSnapshotResult:
    snapshot_id: UUID
    status: str
    assets_created: int
    checks_created: int
    drift_state: AssetStatus
    assets_updated: int = 0
    assets_retired: int = 0
    checks_updated: int = 0
    checks_retired: int = 0
    alias_disable_decision_count: int = 0
    alias_enable_decision_count: int = 0
    published_job_pause_decision_count: int = 0
    published_job_resume_decision_count: int = 0
    asset_ids: list[UUID] = field(default_factory=list)
    check_ids: list[UUID] = field(default_factory=list)
    alias_ids_to_disable: list[UUID] = field(default_factory=list)
    alias_ids_to_enable: list[UUID] = field(default_factory=list)
    published_job_ids_to_pause: list[UUID] = field(default_factory=list)
    published_job_ids_to_resume: list[UUID] = field(default_factory=list)
    retire_reasons: list[dict[str, object]] = field(default_factory=list)
    message: str | None = None
