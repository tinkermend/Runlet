from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps_auth import require_console_user
from app.config.settings import settings
from app.infrastructure.db.console_session import get_console_db
from app.infrastructure.db.models.identity import UserPat
from app.infrastructure.security.pat_auth import issue_pat

router = APIRouter(tags=["platform-auth"])

ConsoleDep = Annotated[Session, Depends(get_console_db)]


def _build_pat_item(record: UserPat) -> dict[str, object | None]:
    return {
        "id": record.id,
        "name": record.name,
        "token_prefix": record.token_prefix,
        "allowed_channels": record.allowed_channels,
        "allowed_actions": record.allowed_actions,
        "allowed_system_ids": record.allowed_system_ids,
        "issued_at": record.issued_at,
        "expires_at": record.expires_at,
        "last_used_at": record.last_used_at,
        "revoked_at": record.revoked_at,
    }


class CreatePatRequest(BaseModel):
    name: str
    expires_in_days: int


class PatListItem(BaseModel):
    id: UUID
    name: str
    token_prefix: str
    allowed_channels: list[str]
    allowed_actions: list[str] | None = None
    allowed_system_ids: list[str] | None = None
    issued_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class CreatePatResponse(PatListItem):
    token: str


@router.post("/pats", response_model=CreatePatResponse, status_code=201)
def create_pat(
    body: CreatePatRequest,
    session: ConsoleDep,
    user=Depends(require_console_user),
) -> CreatePatResponse:
    if body.expires_in_days not in settings.pat_allowed_ttl_days:
        raise HTTPException(
            status_code=422,
            detail=f"expires_in_days must be one of {settings.pat_allowed_ttl_days}",
        )
    try:
        token, record = issue_pat(
            user_id=user.id,
            name=body.name,
            ttl_days=body.expires_in_days,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    data = _build_pat_item(record)
    data["token"] = token
    return CreatePatResponse(**data)


@router.get("/pats", response_model=list[PatListItem])
def list_pats(
    session: ConsoleDep,
    user=Depends(require_console_user),
) -> list[PatListItem]:
    statement = select(UserPat).where(UserPat.user_id == user.id)
    records = session.exec(statement).all()
    return [PatListItem(**_build_pat_item(record)) for record in records]


@router.post("/pats/{pat_id}:revoke", status_code=204)
def revoke_pat(
    pat_id: UUID,
    session: ConsoleDep,
    user=Depends(require_console_user),
) -> None:
    statement = select(UserPat).where(UserPat.id == pat_id, UserPat.user_id == user.id)
    record = session.exec(statement).first()
    if record is None:
        raise HTTPException(status_code=404, detail="PAT not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        session.add(record)
        session.commit()
    return None
