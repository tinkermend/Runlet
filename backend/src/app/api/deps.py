from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.infrastructure.db.session import get_session
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_control_plane_service(session: SessionDep) -> ControlPlaneService:
    return ControlPlaneService(
        repository=SqlControlPlaneRepository(session),
        dispatcher=SqlQueueDispatcher(session),
    )


ControlPlaneServiceDep = Annotated[
    ControlPlaneService,
    Depends(get_control_plane_service),
]
