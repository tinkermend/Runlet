from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
]


class PageCandidate(BaseModel):
    route_path: str
    page_title: str | None = None
    page_summary: str | None = None
    keywords: dict[str, object] | None = None
    discovery_sources: list[str] = Field(default_factory=list)
    entry_candidates: list[dict[str, object]] = Field(default_factory=list)
    context_constraints: dict[str, object] | None = None


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
    stability_score: float | None = None
    usage_description: str | None = None


class CrawlExtractionResult(BaseModel):
    framework_detected: str | None = None
    quality_score: float | None = None
    pages: list[PageCandidate] = Field(default_factory=list)
    menus: list[MenuCandidate] = Field(default_factory=list)
    elements: list[ElementCandidate] = Field(default_factory=list)
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
