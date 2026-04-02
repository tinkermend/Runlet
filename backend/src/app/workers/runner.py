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
            job.status = QueuedJobStatus.SKIPPED.value
            job.started_at = job.started_at or utcnow()
            job.finished_at = utcnow()
            job.failure_message = f"no handler registered for job type: {job.job_type}"
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


def build_worker_handlers(
    *,
    session: Session | AsyncSession,
    auth_service=None,
    crawler_service=None,
    asset_compiler_service=None,
) -> dict[str, JobHandler]:
    from app.domains.control_plane.job_types import (
        ASSET_COMPILE_JOB_TYPE,
        AUTH_REFRESH_JOB_TYPE,
        CRAWL_JOB_TYPE,
    )
    from app.jobs.asset_compile_job import AssetCompileJobHandler
    from app.jobs.auth_refresh_job import AuthRefreshJobHandler
    from app.jobs.crawl_job import CrawlJobHandler

    handlers: dict[str, JobHandler] = {}
    if auth_service is not None:
        handlers[AUTH_REFRESH_JOB_TYPE] = AuthRefreshJobHandler(
            session=session,
            auth_service=auth_service,
        )
    if crawler_service is not None:
        handlers[CRAWL_JOB_TYPE] = CrawlJobHandler(
            session=session,
            crawler_service=crawler_service,
        )
    if asset_compiler_service is not None:
        handlers[ASSET_COMPILE_JOB_TYPE] = AssetCompileJobHandler(
            session=session,
            asset_compiler_service=asset_compiler_service,
        )
    return handlers
