from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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


class AuthRefreshResult(BaseModel):
    system_id: UUID
    status: str
    auth_state_id: UUID | None = None
    message: str | None = None
    validated_at: datetime | None = None
