from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.api.deps_auth import PrincipalDep
from app.domains.control_plane.authorization import authorize
from app.domains.control_plane.schemas import CrawlAccepted, CrawlTriggerRequest


router = APIRouter(tags=["crawl"])


@router.post("/systems/{system_id}/crawl", status_code=202, response_model=CrawlAccepted)
async def trigger_crawl(
    system_id: UUID,
    payload: CrawlTriggerRequest,
    principal: PrincipalDep,
    service: ControlPlaneServiceDep,
) -> CrawlAccepted:
    scope = payload.crawl_scope.strip().lower()
    action = "trigger_incremental_crawl" if scope == "incremental" else "trigger_full_crawl"
    authorize(principal=principal, action=action, system_id=system_id)
    return await service.trigger_crawl(system_id=system_id, payload=payload)
