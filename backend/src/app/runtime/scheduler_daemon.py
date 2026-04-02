from __future__ import annotations

from typing import Protocol

import anyio

from app.config.settings import settings


class SchedulerRuntimeLike(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


async def run_scheduler_daemon(
    *,
    runtime: SchedulerRuntimeLike,
    stop_event: anyio.Event | None = None,
    idle_sleep_seconds: float = 1.0,
) -> None:
    if not settings.scheduler_enabled:
        return

    await runtime.start()
    try:
        if stop_event is None:
            while True:
                await anyio.sleep(idle_sleep_seconds)
            return
        await stop_event.wait()
    finally:
        await runtime.stop()
