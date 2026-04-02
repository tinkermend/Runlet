from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


CaptchaKind = Literal["none", "image_captcha", "slider_captcha", "sms_captcha"]


class DecryptedSystemCredentials(BaseModel):
    system_id: UUID
    login_url: str
    username: str
    password: str
    auth_type: str
    selectors: dict[str, object] | None = None
    secret_ref: str | None = None


class BrowserLoginResult(BaseModel):
    storage_state: dict[str, object]
    auth_mode: str = "storage_state"
    expires_at: datetime | None = None


class CaptchaChallenge(BaseModel):
    kind: CaptchaKind
    image_bytes: bytes | None = None
    puzzle_bytes: bytes | None = None
    metadata: dict[str, object] | None = None


class CaptchaSolution(BaseModel):
    kind: CaptchaKind
    text: str | None = None
    offset_x: int | None = None
    confidence: float | None = None


class AuthRefreshResult(BaseModel):
    system_id: UUID
    status: str
    auth_state_id: UUID | None = None
    message: str | None = None
    validated_at: datetime | None = None
