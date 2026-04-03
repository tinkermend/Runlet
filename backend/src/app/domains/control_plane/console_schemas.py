from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
