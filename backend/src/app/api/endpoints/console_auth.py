from typing import Annotated, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps_auth import require_console_user
from app.config.settings import settings
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.identity import User
from app.infrastructure.security.password_hash import hash_password, verify_password
from app.infrastructure.security.session_auth import (
    SESSION_COOKIE,
    issue_session,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["console-auth"])

ConsoleDep = Annotated[Session, Depends(get_console_db)]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool


class MeResponse(BaseModel):
    username: str


def _ensure_seed_user(session: Session) -> User | None:
    if not settings.console_username or not settings.console_password:
        return None
    existing = session.exec(
        select(User).where(User.username == settings.console_username)
    ).first()
    if existing:
        return existing
    user = User(
        username=settings.console_username,
        password_hash=hash_password(settings.console_password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response, session: ConsoleDep):
    user = session.exec(select(User).where(User.username == body.username)).first()
    if (
        user is None
        and body.username == settings.console_username
        and body.password == settings.console_password
    ):
        user = _ensure_seed_user(session)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User inactive")
    token = issue_session(user=user, session=session)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
    )
    return LoginResponse(ok=True)


@router.post("/logout", response_model=LoginResponse)
async def logout(
    response: Response,
    console_session: Optional[str] = Cookie(default=None),
    session: ConsoleDep,
):
    if console_session:
        revoke_session(token=console_session, session=session)
    response.delete_cookie(SESSION_COOKIE)
    return LoginResponse(ok=True)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(require_console_user)):
    return MeResponse(username=user.username)
