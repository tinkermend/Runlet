from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic import field_validator


def _validate_required_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be empty")
    return normalized


class SystemManifestSection(BaseModel):
    code: str
    name: str
    base_url: str
    framework_type: str

    @field_validator("code", "name", "base_url", "framework_type", mode="before")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value)


class CredentialManifestSection(BaseModel):
    login_url: str
    username: str
    password: str
    auth_type: str
    selectors: dict[str, str] = Field(default_factory=dict)

    @field_validator("login_url", "username", "password", "auth_type", mode="before")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value)


class AuthPolicyManifestSection(BaseModel):
    enabled: bool = True
    schedule_expr: str
    auth_mode: str
    captcha_provider: str = "ddddocr"

    @field_validator("schedule_expr", "auth_mode", mode="before")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value)


class CrawlPolicyManifestSection(BaseModel):
    enabled: bool = True
    schedule_expr: str
    crawl_scope: str = "full"

    @field_validator("schedule_expr", mode="before")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value)


class PublishManifestSection(BaseModel):
    check_goal: str
    schedule_expr: str
    enabled: bool = True

    @field_validator("check_goal", "schedule_expr", mode="before")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_required_text(value)


class WebSystemManifest(BaseModel):
    system: SystemManifestSection
    credential: CredentialManifestSection
    auth_policy: AuthPolicyManifestSection
    crawl_policy: CrawlPolicyManifestSection
    publish: PublishManifestSection
