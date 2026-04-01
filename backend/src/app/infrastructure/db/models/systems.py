from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class System(BaseModel, table=True):
    __tablename__ = "systems"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(max_length=128, unique=True, nullable=False)
    name: str = Field(max_length=255, nullable=False)
    description: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class SystemCredential(BaseModel, table=True):
    __tablename__ = "system_credentials"

    id: int | None = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="systems.id", nullable=False)
    credential_key: str = Field(max_length=128, nullable=False)
    encrypted_payload: str = Field(nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class AuthState(BaseModel, table=True):
    __tablename__ = "auth_states"

    id: int | None = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="systems.id", nullable=False)
    state: str = Field(max_length=64, nullable=False)
    storage_ref: str | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
