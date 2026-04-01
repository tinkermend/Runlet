from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.infrastructure.db.models.jobs import QueuedJob
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthRefreshJobHandler:
    def __init__(self, *, session: Session | AsyncSession, auth_service) -> None:
        self.session = session
        self.auth_service = auth_service

    async def run(self, *, job_id: UUID) -> None:
        job = await self._get(QueuedJob, job_id)
        if job is None:
            raise ValueError(f"queued job {job_id} not found")

        system_id = job.payload.get("system_id")
        if not isinstance(system_id, str):
            await self._mark_failed(job, message="missing system_id in auth refresh job payload")
            return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        await self._commit()

        try:
            result = await self.auth_service.refresh_auth_state(system_id=UUID(system_id))
        except Exception as exc:
            await self._mark_failed(job, message=str(exc))
            return

        if result.status == "success":
            job.status = QueuedJobStatus.COMPLETED.value
            job.failure_message = None
        elif result.status == "retryable_failed":
            job.status = QueuedJobStatus.RETRYABLE_FAILED.value
            job.failure_message = result.message
        else:
            job.status = QueuedJobStatus.FAILED.value
            job.failure_message = result.message

        job.finished_at = utcnow()
        await self._commit()

    async def _mark_failed(self, job: QueuedJob, *, message: str | None) -> None:
        job.status = QueuedJobStatus.FAILED.value
        job.started_at = job.started_at or utcnow()
        job.finished_at = utcnow()
        job.failure_message = message
        await self._commit()

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()
