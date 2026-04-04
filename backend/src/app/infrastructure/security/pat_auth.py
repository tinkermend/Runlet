from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import Session, select

from app.config.settings import settings
from app.infrastructure.db.models.identity import UserPat

_ALGO = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 260_000
_SALT_BYTES = 16
_TOKEN_PREFIX_LENGTH = 16


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_token_prefix(token: str) -> str:
    return token[:_TOKEN_PREFIX_LENGTH]


def hash_pat(token: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_hex(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        token.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"{_ALGO}${iterations}${salt}${derived.hex()}"


def verify_pat(token: str, token_hash: str) -> bool:
    try:
        algo, iterations_raw, salt, digest = token_hash.split("$", 3)
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    try:
        iterations = int(iterations_raw)
    except ValueError:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        token.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(derived.hex(), digest)


def issue_pat(*, user_id: UUID, name: str, ttl_days: int, session: Session) -> tuple[str, UserPat]:
    if ttl_days not in settings.pat_allowed_ttl_days:
        raise ValueError("expires_in_days must be within allowed pat ttl values")
    plaintext = "rpat_" + secrets.token_urlsafe(32)
    token_hash = hash_pat(plaintext)
    expires_at = _utcnow() + timedelta(days=ttl_days)
    record = UserPat(
        user_id=user_id,
        name=name,
        token_prefix=_build_token_prefix(plaintext),
        token_hash=token_hash,
        allowed_channels=["skills"],
        expires_at=expires_at,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return plaintext, record


def get_pat_for_token(*, token: str, session: Session) -> UserPat | None:
    if not token:
        return None
    prefix = _build_token_prefix(token)
    statement = select(UserPat).where(UserPat.token_prefix == prefix)
    now = _utcnow()
    for record in session.exec(statement).all():
        if record.revoked_at is not None:
            continue
        expires_at = _ensure_utc(record.expires_at)
        if expires_at <= now:
            continue
        if not verify_pat(token, record.token_hash):
            continue
        record.last_used_at = now
        session.add(record)
        session.commit()
        session.refresh(record)
        return record
    return None
