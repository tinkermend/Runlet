from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import Session, select

from app.config.settings import settings
from app.domains.asset_compiler.service import AssetCompilerService
from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.domains.auth_service.browser_login import PlaywrightBrowserLoginAdapter
from app.domains.auth_service.service import AuthService
from app.domains.crawler_service.service import CrawlerService, PlaywrightBrowserFactory
from app.domains.runner_service.playwright_runtime import PlaywrightRunnerRuntime
from app.domains.runner_service.service import RunnerService
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.shared.enums import QueuedJobStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class JobHandler(Protocol):
    async def run(self, *, job_id: UUID) -> None: ...


logger = logging.getLogger("runlet.worker")


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
            logger.warning("skipped job %s: no handler for type %s", job.id, job.job_type)
            await self._commit()
            return True

        logger.info("claimed job %s (type=%s)", job.id, job.job_type)
        try:
            await handler.run(job_id=job.id)
            logger.info("completed job %s (type=%s)", job.id, job.job_type)
        except Exception as exc:
            job.status = QueuedJobStatus.FAILED.value
            job.started_at = job.started_at or utcnow()
            job.finished_at = utcnow()
            job.failure_message = f"handler crashed: {exc}"
            logger.exception("failed job %s (type=%s): %s", job.id, job.job_type, exc)
            await self._commit()
        return True

    async def run_forever(
        self,
        poll_interval_ms: int | None = None,
        stop_event: anyio.Event | None = None,
    ) -> None:
        interval_ms = settings.worker_poll_interval_ms if poll_interval_ms is None else poll_interval_ms
        interval_seconds = max(interval_ms, 1) / 1000
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            handled = await self.run_once()
            if handled:
                continue
            if stop_event is not None and stop_event.is_set():
                return
            await anyio.sleep(interval_seconds)

    async def _next_accepted_job(self) -> QueuedJob | None:
        """Claim the next accepted job using SELECT ... FOR UPDATE SKIP LOCKED.

        This prevents multiple workers from claiming the same job when
        running in parallel.  For sync sessions the lock is omitted (single
        worker scenario).
        """
        statement = (
            select(QueuedJob)
            .where(QueuedJob.status == QueuedJobStatus.ACCEPTED.value)
            .order_by(QueuedJob.created_at, QueuedJob.id)
        )
        if isinstance(self.session, AsyncSession):
            result = await self.session.exec(
                statement.with_for_update(skip_locked=True)
            )
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
    control_plane_service=None,
    runner_service=None,
) -> dict[str, JobHandler]:
    from app.domains.control_plane.job_types import (
        ASSET_COMPILE_JOB_TYPE,
        AUTH_REFRESH_JOB_TYPE,
        CRAWL_JOB_TYPE,
        RUN_CHECK_JOB_TYPE,
    )
    from app.jobs.asset_compile_job import AssetCompileJobHandler
    from app.jobs.auth_refresh_job import AuthRefreshJobHandler
    from app.jobs.crawl_job import CrawlJobHandler
    from app.jobs.run_check_job import RunCheckJobHandler

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
            control_plane_service=control_plane_service,
        )
    if runner_service is not None:
        handlers[RUN_CHECK_JOB_TYPE] = RunCheckJobHandler(
            session=session,
            runner_service=runner_service,
            control_plane_service=control_plane_service,
        )
    return handlers


def build_worker_runner(
    *,
    session_factory: async_sessionmaker[AsyncSession] | Callable[[], Session | AsyncSession] | None = None,
) -> WorkerRunner:
    resolved_session_factory = session_factory or create_session_factory()
    session = resolved_session_factory()
    from app.domains.control_plane.repository import SqlControlPlaneRepository
    from app.domains.control_plane.service import ControlPlaneService
    from app.domains.runner_service.scheduler import PublishedJobService
    from app.infrastructure.queue.dispatcher import SqlQueueDispatcher

    dispatcher = SqlQueueDispatcher(session)
    control_plane_service = ControlPlaneService(
        repository=SqlControlPlaneRepository(session),
        dispatcher=dispatcher,
        published_job_service=PublishedJobService(session=session, dispatcher=dispatcher),
    )
    auth_service = AuthService(
        session=session,
        browser_login=PlaywrightBrowserLoginAdapter(),
    )
    crawler_service = CrawlerService(
        session=session,
        browser_factory=PlaywrightBrowserFactory(),
    )
    asset_compiler_service = AssetCompilerService(session=session)
    runner_service = RunnerService(
        session=session,
        runtime=PlaywrightRunnerRuntime(),
    )
    dispatcher = SqlQueueDispatcher(session)
    control_plane_service = ControlPlaneService(
        repository=SqlControlPlaneRepository(session),
        dispatcher=dispatcher,
    )
    return WorkerRunner(
        session=session,
        handlers=build_worker_handlers(
            session=session,
            auth_service=auth_service,
            crawler_service=crawler_service,
            asset_compiler_service=asset_compiler_service,
            control_plane_service=control_plane_service,
            runner_service=runner_service,
        ),
    )


async def run_worker_process(
    *,
    stop_event: anyio.Event | None = None,
    poll_interval_ms: int | None = None,
) -> None:
    runner = build_worker_runner()
    try:
        await runner.run_forever(
            poll_interval_ms=poll_interval_ms,
            stop_event=stop_event,
        )
    finally:
        session = getattr(runner, "session", None)
        if session is None:
            return
        closer = session.close()
        if inspect.isawaitable(closer):
            await closer


def main() -> None:
    anyio.run(run_worker_process)
