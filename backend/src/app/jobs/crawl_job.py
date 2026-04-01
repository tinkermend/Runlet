from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session

from app.domains.control_plane.job_types import ASSET_COMPILE_JOB_TYPE
from app.infrastructure.db.models.jobs import QueuedJob
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class CrawlJobHandler:
    def __init__(self, *, session: Session | AsyncSession, crawler_service) -> None:
        self.session = session
        self.crawler_service = crawler_service

    async def run(self, *, job_id: UUID) -> None:
        job = await self._get(QueuedJob, job_id)
        if job is None:
            raise ValueError(f"queued job {job_id} not found")

        system_id = job.payload.get("system_id")
        crawl_scope = job.payload.get("crawl_scope", "full")
        if not isinstance(system_id, str):
            await self._mark_failed(job, message="missing system_id in crawl job payload")
            return
        if not isinstance(crawl_scope, str) or not crawl_scope.strip():
            await self._mark_failed(job, message="missing crawl_scope in crawl job payload")
            return

        job.status = QueuedJobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        await self._commit()

        try:
            result = await self.crawler_service.run_crawl(
                system_id=UUID(system_id),
                crawl_scope=crawl_scope,
            )
        except Exception as exc:
            await self._mark_failed(job, message=str(exc))
            return

        if result.status != "success" or result.snapshot_id is None:
            await self._mark_failed(job, message=result.message or result.status)
            return

        compile_job = QueuedJob(
            job_type=ASSET_COMPILE_JOB_TYPE,
            payload={
                "snapshot_id": str(result.snapshot_id),
                "compile_scope": "impacted_pages_only",
            },
        )
        self.session.add(compile_job)
        job.status = QueuedJobStatus.COMPLETED.value
        job.failure_message = None
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
