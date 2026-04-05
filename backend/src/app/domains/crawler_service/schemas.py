from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

NavigationTargetKind = Literal[
    "page_route",
    "menu_expand",
    "tab_switch",
    "expand_panel",
    "tree_expand",
    "paginate_probe",
    "open_modal",
    "open_drawer",
    "filter_expand",
    "toggle_view",
]
NavigationMaterializationStatus = Literal[
    "discovered",
    "queued",
    "applied",
    "not_applied",
    "blocked",
    "duplicate",
]
NavigationTargetRejectionReason = Literal[
    "duplicate_target",
    "total_budget_exhausted",
    "route_budget_exhausted",
    "kind_budget_exhausted",
    "parent_budget_exhausted",
    "blocked_by_permission",
    "unsafe_action_rejected",
    "state_transition_not_applied",
]
StateProbeActionType = Literal[
    "tab_switch",
    "expand_panel",
    "open_modal",
    "open_drawer",
    "toggle_view",
    "paginate_probe",
    "tree_expand",
]
ALLOWED_STATE_PROBE_ACTIONS: set[str] = {
    "tab_switch",
    "expand_panel",
    "open_modal",
    "open_drawer",
    "toggle_view",
    "paginate_probe",
    "tree_expand",
}
StateProbeReason = Literal[
    "blocked_by_permission",
    "unsafe_action_rejected",
    "interaction_budget_exhausted",
    "state_signature_duplicate",
    "state_transition_not_applied",
    "state_probe_baseline_degraded",
    "state_probe_actions_degraded",
    "navigation_target_duplicate",
    "route_budget_exhausted",
    "kind_budget_exhausted",
    "parent_budget_exhausted",
    "total_budget_exhausted",
]


class NavigationTargetResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_key: str
    target_kind: NavigationTargetKind
    route_hint: str | None = None
    locator_candidates: list[dict[str, object]] = Field(default_factory=list)
    state_context: dict[str, object] | None = None
    parent_target_key: str | None = None
    discovery_source: str | None = None
    safety_level: str = "readonly"
    materialization_status: NavigationMaterializationStatus = "discovered"
    rejection_reason: NavigationTargetRejectionReason | None = None
    rejection_detail: str | None = None
    metadata: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_status_reason_combination(self) -> "NavigationTargetResult":
        allowed_reasons_by_status = {
            "blocked": {
                "total_budget_exhausted",
                "route_budget_exhausted",
                "kind_budget_exhausted",
                "parent_budget_exhausted",
                "blocked_by_permission",
                "unsafe_action_rejected",
            },
            "duplicate": {"duplicate_target"},
            "not_applied": {"state_transition_not_applied"},
        }
        success_statuses = {"discovered", "queued", "applied"}
        if self.materialization_status in allowed_reasons_by_status and self.rejection_reason is None:
            raise ValueError("rejection_reason is required for blocked, duplicate, and not_applied targets")
        if self.materialization_status in success_statuses and self.rejection_reason is not None:
            raise ValueError("rejection_reason must be empty unless the target was rejected or not applied")
        if self.materialization_status in success_statuses and self.rejection_detail is not None:
            raise ValueError("rejection_detail must be empty for discovered, queued, and applied targets")
        if self.rejection_reason is not None:
            allowed_reasons = allowed_reasons_by_status.get(self.materialization_status)
            if allowed_reasons is None or self.rejection_reason not in allowed_reasons:
                raise ValueError("rejection_reason does not match materialization_status semantics")
        return self


class PageCandidate(BaseModel):
    route_path: str
    page_title: str | None = None
    page_summary: str | None = None
    keywords: dict[str, object] | None = None
    discovery_sources: list[str] = Field(default_factory=list)
    entry_candidates: list[dict[str, object]] = Field(default_factory=list)
    context_constraints: dict[str, object] | None = None
    navigation_diagnostics: dict[str, object] | None = None


class MenuCandidate(BaseModel):
    label: str
    route_path: str | None = None
    depth: int = 0
    sort_order: int = 0
    playwright_locator: str | None = None
    parent_label: str | None = None
    page_route_path: str | None = None
    discovery_sources: list[str] = Field(default_factory=list)
    entry_candidates: list[dict[str, object]] = Field(default_factory=list)
    context_constraints: dict[str, object] | None = None
    navigation_identity: dict[str, object] | None = None
    parent_navigation_identity: dict[str, object] | None = None


class ElementCandidate(BaseModel):
    page_route_path: str
    element_type: str
    state_signature: str | None = None
    state_context: dict[str, object] | None = None
    locator_candidates: list[dict[str, object]] = Field(default_factory=list)
    element_role: str | None = None
    element_text: str | None = None
    attributes: dict[str, object] | None = None
    playwright_locator: str | None = None
    materialized_by: str | None = None
    navigation_diagnostics: dict[str, object] | None = None
    stability_score: float | None = None
    usage_description: str | None = None


class CrawlExtractionResult(BaseModel):
    framework_detected: str | None = None
    quality_score: float | None = None
    pages: list[PageCandidate] = Field(default_factory=list)
    menus: list[MenuCandidate] = Field(default_factory=list)
    elements: list[ElementCandidate] = Field(default_factory=list)
    navigation_targets: list[NavigationTargetResult] = Field(default_factory=list)
    failure_reason: str | None = None
    warning_messages: list[str] = Field(default_factory=list)
    degraded: bool = False


class CrawlRunResult(BaseModel):
    system_id: UUID
    status: str
    snapshot_id: UUID | None = None
    pages_saved: int = 0
    menus_saved: int = 0
    elements_saved: int = 0
    message: str | None = None
    failure_reason: str | None = None
    warning_messages: list[str] = Field(default_factory=list)
    degraded: bool = False
