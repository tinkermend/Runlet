from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ControlPlaneServiceDep
from app.domains.control_plane.schemas import CrawlAccepted, CrawlTriggerRequest


router = APIRouter(tags=["crawl"])


@router.post("/systems/{system_id}/crawl", status_code=202, response_model=CrawlAccepted)
async def trigger_crawl(
    system_id: UUID,
    payload: CrawlTriggerRequest,
    service: ControlPlaneServiceDep,
) -> CrawlAccepted:
    return await service.trigger_crawl(system_id=system_id, payload=payload)
