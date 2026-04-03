from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from app.config.settings import settings
from app.infrastructure.security.console_session import (
    SESSION_COOKIE,
    create_session,
    delete_session,
    get_session,
)

router = APIRouter(prefix="/auth", tags=["console-auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool


class MeResponse(BaseModel):
    username: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response):
    if body.username != settings.console_username or body.password != settings.console_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session(body.username)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=8 * 3600,
    )
    return LoginResponse(ok=True)


@router.post("/logout", response_model=LoginResponse)
async def logout(
    response: Response,
    console_session: Optional[str] = Cookie(default=None),
):
    if console_session:
        delete_session(console_session)
    response.delete_cookie(SESSION_COOKIE)
    return LoginResponse(ok=True)


@router.get("/me", response_model=MeResponse)
async def me(console_session: Optional[str] = Cookie(default=None)):
    if not console_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = get_session(console_session)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired")
    return MeResponse(username=session["username"])
