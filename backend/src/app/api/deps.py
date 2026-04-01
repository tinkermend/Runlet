from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.infrastructure.db.session import create_db_engine
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher


async def get_control_plane_service() -> AsyncIterator[ControlPlaneService]:
    engine = create_db_engine().sync_engine
    with Session(engine) as session:
        yield ControlPlaneService(
            repository=SqlControlPlaneRepository(session),
            dispatcher=SqlQueueDispatcher(session),
        )


ControlPlaneServiceDep = Annotated[
    ControlPlaneService,
    Depends(get_control_plane_service),
]
