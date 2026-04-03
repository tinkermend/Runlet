from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.asset_compiler.service import AssetCompilerService
from app.domains.auth_service.browser_login import PlaywrightBrowserLoginAdapter
from app.domains.auth_service.crypto import CredentialCrypto
from app.domains.auth_service.service import AuthService
from app.domains.control_plane.job_types import (
    ASSET_COMPILE_JOB_TYPE,
    AUTH_REFRESH_JOB_TYPE,
    CRAWL_JOB_TYPE,
)
from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.domains.control_plane.service import ControlPlaneService
from app.domains.control_plane.system_admin_service import SystemAdminService
from app.domains.control_plane.system_admin_repository import SqlSystemAdminRepository
from app.domains.crawler_service.service import CrawlerService, PlaywrightBrowserFactory
from app.domains.runner_service.scheduler import PublishedJobService
from app.domains.runner_service.script_renderer import ScriptRenderer
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.workers.runner import build_worker_handlers


class InProcessFormalJobExecutor:
    def __init__(self, *, handlers: dict[str, object]) -> None:
        self.handlers = handlers

    async def run_auth_refresh(self, job_id) -> None:
        handler = self.handlers[AUTH_REFRESH_JOB_TYPE]
        await handler.run(job_id=job_id)

    async def run_crawl(self, job_id) -> None:
        handler = self.handlers[CRAWL_JOB_TYPE]
        await handler.run(job_id=job_id)

    async def run_asset_compile(self, job_id) -> None:
        handler = self.handlers[ASSET_COMPILE_JOB_TYPE]
        await handler.run(job_id=job_id)


def build_system_admin_service(
    *,
    session,
    scheduler: BaseScheduler,
    crypto: CredentialCrypto | None = None,
    auth_service=None,
    crawler_service=None,
    asset_compiler_service=None,
) -> SystemAdminService:
    dispatcher = SqlQueueDispatcher(session)
    scheduler_registry = SchedulerRegistry(
        session=session,
        scheduler=scheduler,
    )
    control_plane_service = ControlPlaneService(
        repository=SqlControlPlaneRepository(session),
        dispatcher=dispatcher,
        script_renderer=ScriptRenderer(session=session),
        published_job_service=PublishedJobService(session=session, dispatcher=dispatcher),
        scheduler_registry=scheduler_registry,
    )
    resolved_auth_service = auth_service or AuthService(
        session=session,
        browser_login=PlaywrightBrowserLoginAdapter(),
    )
    resolved_crawler_service = crawler_service or CrawlerService(
        session=session,
        browser_factory=PlaywrightBrowserFactory(),
    )
    resolved_asset_compiler_service = asset_compiler_service or AssetCompilerService(
        session=session
    )
    handlers = build_worker_handlers(
        session=session,
        auth_service=resolved_auth_service,
        crawler_service=resolved_crawler_service,
        asset_compiler_service=resolved_asset_compiler_service,
        control_plane_service=control_plane_service,
    )
    return SystemAdminService(
        repository=SqlSystemAdminRepository(session),
        control_plane_service=control_plane_service,
        crypto=crypto,
        job_executor=InProcessFormalJobExecutor(handlers=handlers),
        scheduler_registry=scheduler_registry,
    )


@asynccontextmanager
async def bootstrap_system_admin_service(
    *,
    scheduler: BaseScheduler | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    crypto: CredentialCrypto | None = None,
) -> AsyncIterator[SystemAdminService]:
    owns_scheduler = scheduler is None
    resolved_scheduler = scheduler or BackgroundScheduler(timezone="UTC")
    if owns_scheduler and not resolved_scheduler.running:
        resolved_scheduler.start(paused=True)

    resolved_session_factory = session_factory or create_session_factory()
    async with resolved_session_factory() as session:
        yield build_system_admin_service(
            session=session,
            scheduler=resolved_scheduler,
            crypto=crypto,
        )

    if owns_scheduler and resolved_scheduler.running:
        resolved_scheduler.shutdown(wait=False)
