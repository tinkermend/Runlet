from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class PageCandidate(BaseModel):
    route_path: str
    page_title: str | None = None
    page_summary: str | None = None
    keywords: dict[str, object] | None = None


class MenuCandidate(BaseModel):
    label: str
    route_path: str | None = None
    depth: int = 0
    sort_order: int = 0
    playwright_locator: str | None = None
    parent_label: str | None = None
    page_route_path: str | None = None


class ElementCandidate(BaseModel):
    page_route_path: str
    element_type: str
    element_role: str | None = None
    element_text: str | None = None
    attributes: dict[str, object] | None = None
    playwright_locator: str | None = None
    stability_score: float | None = None
    usage_description: str | None = None


class CrawlExtractionResult(BaseModel):
    framework_detected: str | None = None
    quality_score: float | None = None
    pages: list[PageCandidate] = []
    menus: list[MenuCandidate] = []
    elements: list[ElementCandidate] = []


class CrawlRunResult(BaseModel):
    system_id: UUID
    status: str
    snapshot_id: UUID | None = None
    pages_saved: int = 0
    menus_saved: int = 0
    elements_saved: int = 0
    message: str | None = None
