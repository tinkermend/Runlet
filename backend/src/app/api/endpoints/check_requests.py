from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import (
    CheckRequestAccepted,
    CheckRequestStatus,
    CreateCheckRequest,
)
from app.domains.runner_service.result_views import CheckResultView


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


@router.get("/{request_id}/result", response_model=CheckResultView)
async def get_check_request_result(
    request_id: UUID,
    service: ControlPlaneServiceDep,
) -> CheckResultView:
    return await service.get_check_request_result(request_id)
