import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

# In-memory session store (sufficient for single-process console)
_sessions: dict[str, dict] = {}

SESSION_COOKIE = "console_session"
SESSION_TTL_HOURS = 8


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "created_at": datetime.now(timezone.utc),
    }
    return token


def get_session(token: str) -> Optional[dict]:
    session = _sessions.get(token)
    if session is None:
        return None
    age = datetime.now(timezone.utc) - session["created_at"]
    if age > timedelta(hours=SESSION_TTL_HOURS):
        del _sessions[token]
        return None
    return session


def delete_session(token: str) -> None:
    _sessions.pop(token, None)
