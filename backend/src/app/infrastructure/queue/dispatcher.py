from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.infrastructure.db.models.jobs import QueuedJob


class QueueDispatcher(Protocol):
    async def enqueue(self, *, job_type: str, payload: dict[str, Any]) -> UUID: ...


class SqlQueueDispatcher:
    def __init__(self, session: Session | AsyncSession) -> None:
        self.session = session

    async def enqueue(self, *, job_type: str, payload: dict[str, Any]) -> UUID:
        job = QueuedJob(job_type=job_type, payload=payload)
        self.session.add(job)
        if isinstance(self.session, AsyncSession):
            await self.session.flush()
        else:
            self.session.flush()
        return job.id
