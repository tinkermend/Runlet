from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlmodel import Session

from app.domains.control_plane.authorization import Principal
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.identity import User
from app.infrastructure.security.pat_auth import get_pat_for_token
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


def _parse_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    prefix, _, token = authorization.partition(" ")
    if prefix.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    return token.strip()


def resolve_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    console_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: Session = Depends(get_console_db),
) -> Principal:
    bearer = _parse_bearer_token(authorization)
    if bearer:
        pat = get_pat_for_token(token=bearer, session=session)
        if pat is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return Principal(
            channel="skills",
            subject_type="human",
            subject_id=f"user:{pat.user_id}",
            user_id=pat.user_id,
        )

    if console_session:
        user = get_user_for_session(token=console_session, session=session)
        if user is None:
            raise HTTPException(status_code=401, detail="Session expired")
        return Principal(
            channel="web_console",
            subject_type="human",
            subject_id=f"user:{user.id}",
            user_id=user.id,
        )

    raise HTTPException(status_code=401, detail="Not authenticated")


PrincipalDep = Annotated[Principal, Depends(resolve_principal)]
