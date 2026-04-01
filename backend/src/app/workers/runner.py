from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

from app.infrastructure.db.models.jobs import QueuedJob
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobHandler(Protocol):
    async def run(self, *, job_id: UUID) -> None: ...


class WorkerRunner:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        handlers: dict[str, JobHandler],
    ) -> None:
        self.session = session
        self.handlers = handlers

    async def run_once(self) -> bool:
        job = await self._next_accepted_job()
        if job is None:
            return False

        handler = self.handlers.get(job.job_type)
        if handler is None:
            job.status = QueuedJobStatus.FAILED.value
            job.started_at = job.started_at or utcnow()
            job.finished_at = utcnow()
            job.failure_message = f"unsupported job type: {job.job_type}"
            await self._commit()
            return True

        await handler.run(job_id=job.id)
        return True

    async def _next_accepted_job(self) -> QueuedJob | None:
        statement = (
            select(QueuedJob)
            .where(QueuedJob.status == QueuedJobStatus.ACCEPTED.value)
            .order_by(QueuedJob.created_at, QueuedJob.id)
        )
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(statement)
            return result.first()
        return self.session.exec(statement).first()

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()
