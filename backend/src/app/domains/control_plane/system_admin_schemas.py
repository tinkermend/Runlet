from __future__ import annotations

from pydantic import BaseModel, Field


class SystemManifestSection(BaseModel):
    code: str
    name: str
    base_url: str
    framework_type: str


class CredentialManifestSection(BaseModel):
    login_url: str
    username: str
    password: str
    auth_type: str
    selectors: dict[str, str] = Field(default_factory=dict)


class AuthPolicyManifestSection(BaseModel):
    enabled: bool = True
    schedule_expr: str
    auth_mode: str
    captcha_provider: str = "ddddocr"


class CrawlPolicyManifestSection(BaseModel):
    enabled: bool = True
    schedule_expr: str
    crawl_scope: str = "full"


class PublishManifestSection(BaseModel):
    check_goal: str
    schedule_expr: str
    enabled: bool = True


class WebSystemManifest(BaseModel):
    system: SystemManifestSection
    credential: CredentialManifestSection
    auth_policy: AuthPolicyManifestSection
    crawl_policy: CrawlPolicyManifestSection
    publish: PublishManifestSection
