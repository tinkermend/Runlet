from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.domains.runner_service.scheduler import PublishedJobService
from app.domains.runner_service.script_renderer import ScriptRenderer
from app.infrastructure.db.session import get_session
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_control_plane_service(session: SessionDep) -> ControlPlaneService:
    dispatcher = SqlQueueDispatcher(session)
    return ControlPlaneService(
        repository=SqlControlPlaneRepository(session),
        dispatcher=dispatcher,
        script_renderer=ScriptRenderer(session=session),
        published_job_service=PublishedJobService(session=session, dispatcher=dispatcher),
    )


ControlPlaneServiceDep = Annotated[
    ControlPlaneService,
    Depends(get_control_plane_service),
]
