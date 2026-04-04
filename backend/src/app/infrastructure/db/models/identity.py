from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field

from app.infrastructure.db.base import BaseModel


json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(BaseModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=128)
    password_hash: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    status: str = Field(
        default="active",
        sa_column=sa.Column(
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            onupdate=utcnow,
        ),
    )


class UserSession(BaseModel, table=True):
    __tablename__ = "user_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    session_token_hash: str = Field(sa_column=sa.Column(sa.Text(), nullable=False, unique=True))
    issued_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    expires_at: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False)
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )


class UserPat(BaseModel, table=True):
    __tablename__ = "user_pats"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=128)
    token_prefix: str = Field(max_length=16, index=True)
    token_hash: str = Field(sa_column=sa.Column(sa.Text(), nullable=False, unique=True))
    allowed_channels: list[str] = Field(
        default_factory=lambda: ["skills"],
        sa_column=sa.Column(json_type, nullable=False),
    )
    allowed_actions: list[str] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    allowed_system_ids: list[str] | None = Field(
        default=None,
        sa_column=sa.Column(json_type, nullable=True),
    )
    issued_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    expires_at: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False)
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True),
    )


class AuthAuditLog(BaseModel, table=True):
    __tablename__ = "auth_audit_logs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    subject_type: str = Field(max_length=16)
    subject_id: str = Field(max_length=64)
    channel: str = Field(max_length=32)
    system_id: UUID | None = Field(default=None, foreign_key="systems.id", index=True)
    action: str = Field(max_length=128)
    decision: str = Field(max_length=16)
    reason: str | None = Field(default=None, max_length=255)
    request_id: str | None = Field(default=None, max_length=64)
    ip: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
