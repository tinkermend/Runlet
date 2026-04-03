from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

CHECK_TYPE_LABELS: dict[str, str] = {
    "menu_completeness": "菜单完整性",
    "element_existence": "页面元素存在性",
    "login_flow": "登录流程",
    "table_render": "表格渲染",
    "form_submit": "表单提交",
    "page_load": "页面加载",
}


class DashboardSummary(BaseModel):
    today_runs: int
    active_tasks: int
    systems_count: int
    recent_failures_24h: int
    recent_exceptions: list[dict]


class SystemItem(BaseModel):
    id: UUID
    name: str
    base_url: str
    status: str  # ready / onboarding / failed
    task_count: int


class SystemCreateRequest(BaseModel):
    name: str
    base_url: str
    auth_type: str = "none"  # none / username_password / cookie
    username: str | None = None
    password: str | None = None


class SystemCreated(BaseModel):
    id: UUID
    name: str
    base_url: str
    status: str


class RunResultItem(BaseModel):
    id: UUID
    task_name: str
    system_name: str
    status: str
    duration_ms: int | None
    created_at: datetime


class PaginatedResults(BaseModel):
    items: list[RunResultItem]
    total: int
    page: int
    page_size: int


class TaskItem(BaseModel):
    id: str
    name: str
    system_name: str
    status: str  # active / disabled
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    schedule_preset: str  # hourly / daily / manual


class TaskCreateRequest(BaseModel):
    name: str
    system_id: UUID
    check_types: list[str]  # e.g. ["menu_completeness", "element_existence"]
    schedule_preset: str = "manual"  # hourly / daily / manual
    timeout_seconds: int = 30


class TaskCreated(BaseModel):
    id: str
    name: str


class TaskDetail(BaseModel):
    id: str
    name: str
    system_name: str
    status: str
    schedule_preset: str
    check_types: list[str]
    recent_runs: list[RunResultItem]  # last 10 runs


class WizardOptions(BaseModel):
    systems: list[SystemItem]
    check_types: list[str]


class TriggerResponse(BaseModel):
    ok: bool
    run_id: Optional[str] = None


class AssetItem(BaseModel):
    id: UUID
    check_type_label: str
    version: str
    status: str


class PageGroup(BaseModel):
    page_name: str
    assets: list[AssetItem]


class SystemAssetGroup(BaseModel):
    system_id: UUID
    system_name: str
    pages: list[PageGroup]


class AssetDetail(BaseModel):
    id: UUID
    page_name: str
    system_name: str
    check_type_label: str
    version: str
    status: str
    collected_at: Optional[datetime] = None
    raw_facts: Optional[dict] = None
