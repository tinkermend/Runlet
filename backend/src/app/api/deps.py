from __future__ import annotations

from typing import Annotated

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.domains.control_plane.service import ControlPlaneService
from app.domains.runner_service.scheduler import PublishedJobService
from app.domains.runner_service.script_renderer import ScriptRenderer
from app.infrastructure.db.session import get_session
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher


SessionDep = Annotated[AsyncSession, Depends(get_session)]
_registry_scheduler: BackgroundScheduler | None = None


def get_registry_scheduler() -> BackgroundScheduler:
    global _registry_scheduler

    if _registry_scheduler is None:
        _registry_scheduler = BackgroundScheduler(timezone="UTC")
        _registry_scheduler.start(paused=True)
    return _registry_scheduler


RegistrySchedulerDep = Annotated[BackgroundScheduler, Depends(get_registry_scheduler)]


async def get_control_plane_service(
    session: SessionDep,
    registry_scheduler: RegistrySchedulerDep,
) -> ControlPlaneService:
    dispatcher = SqlQueueDispatcher(session)
    published_job_service = PublishedJobService(session=session, dispatcher=dispatcher)
    scheduler_registry = SchedulerRegistry(
        session=session,
        scheduler=registry_scheduler,
    )
    return ControlPlaneService(
        repository=SqlControlPlaneRepository(session),
        dispatcher=dispatcher,
        script_renderer=ScriptRenderer(session=session),
        published_job_service=published_job_service,
        scheduler_registry=scheduler_registry,
    )


ControlPlaneServiceDep = Annotated[
    ControlPlaneService,
    Depends(get_control_plane_service),
]
