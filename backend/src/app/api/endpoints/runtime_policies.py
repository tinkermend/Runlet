from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import (
    SystemAuthPolicyRead,
    SystemCrawlPolicyRead,
    UpdateSystemAuthPolicy,
    UpdateSystemCrawlPolicy,
)


router = APIRouter(tags=["runtime-policies"])


@router.get("/systems/{system_id}/auth-policy", response_model=SystemAuthPolicyRead)
async def get_system_auth_policy(
    system_id: UUID,
    service: ControlPlaneServiceDep,
) -> SystemAuthPolicyRead:
    return await service.get_system_auth_policy(system_id=system_id)


@router.put("/systems/{system_id}/auth-policy", response_model=SystemAuthPolicyRead)
async def upsert_system_auth_policy(
    system_id: UUID,
    payload: UpdateSystemAuthPolicy,
    service: ControlPlaneServiceDep,
) -> SystemAuthPolicyRead:
    return await service.upsert_system_auth_policy(system_id=system_id, payload=payload)


@router.get("/systems/{system_id}/crawl-policy", response_model=SystemCrawlPolicyRead)
async def get_system_crawl_policy(
    system_id: UUID,
    service: ControlPlaneServiceDep,
) -> SystemCrawlPolicyRead:
    return await service.get_system_crawl_policy(system_id=system_id)


@router.put("/systems/{system_id}/crawl-policy", response_model=SystemCrawlPolicyRead)
async def upsert_system_crawl_policy(
    system_id: UUID,
    payload: UpdateSystemCrawlPolicy,
    service: ControlPlaneServiceDep,
) -> SystemCrawlPolicyRead:
    return await service.upsert_system_crawl_policy(system_id=system_id, payload=payload)
