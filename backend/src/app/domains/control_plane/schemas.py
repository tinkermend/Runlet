from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, field_validator


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
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("page_hint", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("strictness", "request_source", mode="before")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


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
