from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import anyio
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.settings import settings
from app.domains.control_plane.scheduler_registry import SchedulerRegistry
from app.infrastructure.db.session import create_session_factory
from app.runtime.scheduler_runtime import SchedulerRuntime


class SchedulerRuntimeLike(Protocol):
    async def start(self) -> None: ...

    async def reload_all(self) -> None: ...

    async def stop(self) -> None: ...


def build_scheduler_runtime(
    *,
    session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession] | None = None,
    scheduler: BackgroundScheduler | None = None,
) -> SchedulerRuntime:
    resolved_session_factory = session_factory or create_session_factory()
    resolved_scheduler = scheduler or BackgroundScheduler(timezone=settings.scheduler_timezone)
    return SchedulerRuntime(
        scheduler_registry=SchedulerRegistry(
            scheduler=resolved_scheduler,
            session_factory=resolved_session_factory,
        ),
        session_factory=resolved_session_factory,
    )


async def run_scheduler_daemon(
    *,
    runtime: SchedulerRuntimeLike,
    stop_event: anyio.Event | None = None,
    idle_sleep_seconds: float = 1.0,
    reload_interval_seconds: float | None = None,
) -> None:
    if not settings.scheduler_enabled:
        return

    resolved_reload_interval_seconds = (
        settings.scheduler_reload_interval_seconds
        if reload_interval_seconds is None
        else reload_interval_seconds
    )
    await runtime.start()
    try:
        while True:
            wait_seconds = (
                resolved_reload_interval_seconds
                if resolved_reload_interval_seconds > 0
                else idle_sleep_seconds
            )
            if stop_event is None:
                await anyio.sleep(wait_seconds)
            else:
                with anyio.move_on_after(wait_seconds):
                    await stop_event.wait()
                if stop_event.is_set():
                    return

            if resolved_reload_interval_seconds > 0:
                await runtime.reload_all()
    finally:
        await runtime.stop()


async def run_scheduler_process(
    *,
    stop_event: anyio.Event | None = None,
    idle_sleep_seconds: float = 1.0,
    reload_interval_seconds: float | None = None,
) -> None:
    runtime = build_scheduler_runtime()
    await run_scheduler_daemon(
        runtime=runtime,
        stop_event=stop_event,
        idle_sleep_seconds=idle_sleep_seconds,
        reload_interval_seconds=reload_interval_seconds,
    )


def main() -> None:
    anyio.run(run_scheduler_process)
