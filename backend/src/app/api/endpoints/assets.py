from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import CompileAssetsAccepted, CompileAssetsRequest


router = APIRouter(tags=["assets"])


@router.post("/snapshots/{snapshot_id}/compile-assets", status_code=202, response_model=CompileAssetsAccepted)
async def compile_assets(
    snapshot_id: UUID,
    payload: CompileAssetsRequest,
    service: ControlPlaneServiceDep,
) -> CompileAssetsAccepted:
    return await service.compile_assets(snapshot_id=snapshot_id, payload=payload)
