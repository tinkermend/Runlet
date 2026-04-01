from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import (
    CheckRequestAccepted,
    CheckRequestStatus,
    CreateCheckRequest,
)


router = APIRouter(prefix="/check-requests", tags=["check-requests"])


@router.post("", status_code=202, response_model=CheckRequestAccepted)
async def create_check_request(
    payload: CreateCheckRequest,
    service: ControlPlaneServiceDep,
) -> CheckRequestAccepted:
    return await service.submit_check_request(**payload.model_dump())


@router.get("/{request_id}", response_model=CheckRequestStatus)
async def get_check_request(
    request_id: UUID,
    service: ControlPlaneServiceDep,
) -> CheckRequestStatus:
    return await service.get_check_request_status(request_id)
