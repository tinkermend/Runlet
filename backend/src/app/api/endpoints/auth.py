from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.api.deps_auth import PrincipalDep
from app.domains.control_plane.authorization import authorize
from app.domains.control_plane.schemas import AuthRefreshAccepted


router = APIRouter(tags=["auth"])


@router.post("/systems/{system_id}/auth:refresh", status_code=202, response_model=AuthRefreshAccepted)
async def refresh_auth(
    system_id: UUID,
    principal: PrincipalDep,
    service: ControlPlaneServiceDep,
) -> AuthRefreshAccepted:
    authorize(principal=principal, action="refresh_auth", system_id=system_id)
    return await service.refresh_auth(system_id=system_id)
