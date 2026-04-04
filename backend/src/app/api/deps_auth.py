from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException
from sqlmodel import Session

from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.identity import User
from app.infrastructure.security.session_auth import SESSION_COOKIE, get_user_for_session


def require_console_user(
    console_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_console_db),
) -> User:
    if not console_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = get_user_for_session(token=console_session, session=session)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired")
    return user
