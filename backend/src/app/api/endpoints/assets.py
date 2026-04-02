from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import CompileAssetsAccepted, CompileAssetsRequest
from app.domains.runner_service.scheduler import (
    CreatePublishedJobRequest,
    PublishedJobCreated,
    PublishedJobRunsList,
    PublishedJobTriggerAccepted,
)


router = APIRouter(tags=["assets"])


@router.post("/snapshots/{snapshot_id}/compile-assets", status_code=202, response_model=CompileAssetsAccepted)
async def compile_assets(
    snapshot_id: UUID,
    payload: CompileAssetsRequest,
    service: ControlPlaneServiceDep,
) -> CompileAssetsAccepted:
    return await service.compile_assets(snapshot_id=snapshot_id, payload=payload)


@router.post("/published-jobs", status_code=201, response_model=PublishedJobCreated)
async def create_published_job(
    payload: CreatePublishedJobRequest,
    service: ControlPlaneServiceDep,
) -> PublishedJobCreated:
    return await service.create_published_job(payload=payload)


@router.post(
    "/published-jobs/{published_job_id}:trigger",
    status_code=202,
    response_model=PublishedJobTriggerAccepted,
)
async def trigger_published_job(
    published_job_id: UUID,
    service: ControlPlaneServiceDep,
) -> PublishedJobTriggerAccepted:
    return await service.trigger_published_job(published_job_id=published_job_id)


@router.get(
    "/published-jobs/{published_job_id}/runs",
    response_model=PublishedJobRunsList,
)
async def list_published_job_runs(
    published_job_id: UUID,
    service: ControlPlaneServiceDep,
) -> PublishedJobRunsList:
    return await service.list_published_job_runs(published_job_id=published_job_id)
