from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import Session

from app.config.settings import settings
from app.infrastructure.db.models.identity import UserPat

_ALGO = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 260_000
_SALT_BYTES = 16


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    token_prefix = plaintext[:16]
    record = UserPat(
        user_id=user_id,
        name=name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        allowed_channels=["skills"],
        expires_at=expires_at,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return plaintext, record
