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
    asset_ids: list[UUID] = field(default_factory=list)
    check_ids: list[UUID] = field(default_factory=list)
    message: str | None = None
