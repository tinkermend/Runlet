from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import AuthRefreshAccepted


router = APIRouter(tags=["auth"])


@router.post("/systems/{system_id}/auth:refresh", status_code=202, response_model=AuthRefreshAccepted)
async def refresh_auth(
    system_id: UUID,
    service: ControlPlaneServiceDep,
) -> AuthRefreshAccepted:
    return await service.refresh_auth(system_id=system_id)
