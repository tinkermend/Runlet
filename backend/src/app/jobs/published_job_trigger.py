from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.domains.control_plane.job_types import RUN_CHECK_JOB_TYPE
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob
from app.infrastructure.queue.dispatcher import QueueDispatcher
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class PublishedJobTrigger:
    def __init__(
        self,
        *,
        session: Session | AsyncSession,
        dispatcher: QueueDispatcher,
    ) -> None:
        self.session = session
        self.dispatcher = dispatcher

    async def trigger(
        self,
        *,
        published_job: PublishedJob,
        trigger_source: str,
        scheduled_at: datetime | None = None,
    ) -> tuple[JobRun, UUID]:
        run_scheduled_at = scheduled_at or utcnow()
        job_run = JobRun(
            published_job_id=published_job.id,
            trigger_source=trigger_source,
            run_status=QueuedJobStatus.ACCEPTED.value,
            scheduled_at=run_scheduled_at,
        )
        self.session.add(job_run)
        await self._flush()

        payload = {
            "page_check_id": str(published_job.page_check_id),
            "execution_track": "precompiled",
            "published_job_id": str(published_job.id),
            "job_run_id": str(job_run.id),
            "script_render_id": str(published_job.script_render_id)
            if published_job.script_render_id is not None
            else None,
            "asset_version": published_job.asset_version,
            "runtime_policy": published_job.runtime_policy,
            "schedule_expr": published_job.schedule_expr,
            "trigger_source": trigger_source,
            "scheduled_at": run_scheduled_at.isoformat(),
        }
        queued_job_id = await self.dispatcher.enqueue(
            job_type=RUN_CHECK_JOB_TYPE,
            payload=payload,
        )
        queued_job = await self._get(QueuedJob, queued_job_id)
        if queued_job is not None:
            queued_job.payload = {**queued_job.payload, "queued_job_id": str(queued_job_id)}
        await self._commit()
        await self._refresh(job_run)
        return job_run, queued_job_id

    async def _get(self, model, identifier):
        if isinstance(self.session, AsyncSession):
            return await self.session.get(model, identifier)
        return self.session.get(model, identifier)

    async def _flush(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.flush()
            return
        self.session.flush()

    async def _commit(self) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.commit()
            return
        self.session.commit()

    async def _refresh(self, model) -> None:
        if isinstance(self.session, AsyncSession):
            await self.session.refresh(model)
            return
        self.session.refresh(model)
