from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, field_validator


def _validate_required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be empty")
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_positive_int(value: int) -> int:
    if value <= 0:
        raise ValueError("value must be greater than 0")
    return value


class CreateCheckRequest(BaseModel):
    system_hint: str
    page_hint: str | None = None
    check_goal: str
    strictness: str = "balanced"
    time_budget_ms: int = 20_000
    request_source: str = "api"

    @field_validator("system_hint", "check_goal", mode="before")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value)

    @field_validator("page_hint", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("strictness", "request_source", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _validate_required_text(value)

    @field_validator("time_budget_ms")
    @classmethod
    def validate_time_budget(cls, value: int) -> int:
        return _validate_positive_int(value)


class RunPageCheck(BaseModel):
    strictness: str = "balanced"
    time_budget_ms: int = 20_000
    triggered_by: str = "manual"

    @field_validator("strictness", "triggered_by", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _validate_required_text(value)

    @field_validator("time_budget_ms")
    @classmethod
    def validate_time_budget(cls, value: int) -> int:
        return _validate_positive_int(value)


class CheckRequestAccepted(BaseModel):
    request_id: UUID
    plan_id: UUID
    page_check_id: UUID | None
    execution_track: str
    auth_policy: str
    job_id: UUID
    status: str = "accepted"


class CheckRequestStatus(BaseModel):
    request_id: UUID
    plan_id: UUID | None = None
    page_check_id: UUID | None = None
    execution_track: str | None = None
    auth_policy: str | None = None
    status: str = "accepted"


class PageAssetCheckItem(BaseModel):
    id: UUID
    page_asset_id: UUID
    check_code: str
    goal: str
    module_plan_id: UUID | None = None
    status: str


class PageAssetChecksList(BaseModel):
    page_asset_id: UUID
    checks: list[PageAssetCheckItem]


class AuthRefreshAccepted(BaseModel):
    system_id: UUID
    job_id: UUID
    status: str = "accepted"
    job_type: str = "auth_refresh"


class CrawlTriggerRequest(BaseModel):
    crawl_scope: str = "full"
    framework_hint: str = "auto"
    max_pages: int = 50

    @field_validator("crawl_scope", "framework_hint", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _validate_required_text(value)

    @field_validator("max_pages")
    @classmethod
    def validate_max_pages(cls, value: int) -> int:
        return _validate_positive_int(value)


class CrawlAccepted(BaseModel):
    system_id: UUID
    job_id: UUID
    status: str = "accepted"
    job_type: str = "crawl"
    snapshot_pending: bool = True


class CompileAssetsRequest(BaseModel):
    compile_scope: str = "impacted_pages_only"

    @field_validator("compile_scope", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _validate_required_text(value)


class CompileAssetsAccepted(BaseModel):
    snapshot_id: UUID
    job_id: UUID
    status: str = "accepted"
    job_type: str = "asset_compile"
