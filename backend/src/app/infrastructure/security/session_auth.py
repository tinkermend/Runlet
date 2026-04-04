from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.config.settings import settings
from app.infrastructure.db.models.identity import User, UserSession

SESSION_COOKIE = "console_session"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hash_session_token(token: str) -> str:
    payload = f"{settings.session_secret}:{token}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def issue_session(*, user: User, session: Session) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_session_token(token)
    expires_at = _utcnow() + timedelta(hours=settings.session_ttl_hours)
    record = UserSession(
        user_id=user.id,
        session_token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(record)
    session.commit()
    return token


def revoke_session(*, token: str, session: Session) -> None:
    token_hash = _hash_session_token(token)
    record = session.exec(
        select(UserSession).where(UserSession.session_token_hash == token_hash)
    ).first()
    if not record:
        return
    if record.revoked_at is None:
        record.revoked_at = _utcnow()
        session.add(record)
        session.commit()


def get_user_for_session(*, token: str, session: Session) -> User | None:
    token_hash = _hash_session_token(token)
    record = session.exec(
        select(UserSession).where(UserSession.session_token_hash == token_hash)
    ).first()
    if not record:
        return None

    now = _utcnow()
    if record.revoked_at is not None:
        return None
    expires_at = _ensure_utc(record.expires_at)
    if expires_at <= now:
        record.revoked_at = now
        session.add(record)
        session.commit()
        return None

    user = session.get(User, record.user_id)
    if not user or user.status != "active":
        return None
    return user
