from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import (
    CheckRequestAccepted,
    PageAssetChecksList,
    RunPageCheck,
)


router = APIRouter(tags=["page-checks"])


@router.post("/page-checks/{page_check_id}:run", status_code=202, response_model=CheckRequestAccepted)
async def run_page_check(
    page_check_id: UUID,
    payload: RunPageCheck,
    service: ControlPlaneServiceDep,
) -> CheckRequestAccepted:
    return await service.run_page_check(page_check_id=page_check_id, **payload.model_dump())


@router.get("/page-assets/{page_asset_id}/checks", response_model=PageAssetChecksList)
async def list_page_asset_checks(
    page_asset_id: UUID,
    service: ControlPlaneServiceDep,
) -> PageAssetChecksList:
    return await service.list_page_asset_checks(page_asset_id)
