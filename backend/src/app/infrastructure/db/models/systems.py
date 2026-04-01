from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel
from app.shared.enums import AuthStateStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


class System(BaseModel, table=True):
    __tablename__ = "systems"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=255)
    base_url: str = Field(max_length=512)
    framework_type: str = Field(max_length=32)


class SystemCredential(BaseModel, table=True):
    __tablename__ = "system_credentials"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    login_url: str = Field(max_length=512)
    login_username_encrypted: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    login_password_encrypted: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    login_auth_type: str = Field(max_length=32)
    login_selectors: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    secret_ref: str | None = Field(default=None, max_length=255)


class AuthState(BaseModel, table=True):
    __tablename__ = "auth_states"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    status: str = Field(
        default=AuthStateStatus.PENDING.value,
        sa_column=sa.Column(
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    storage_state: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    cookies: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    local_storage: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    session_storage: dict[str, object] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    token_fingerprint: str | None = Field(default=None, max_length=255)
    auth_mode: str = Field(max_length=32)
    is_valid: bool = Field(default=False)
    validated_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
