from __future__ import annotations

from dataclasses import dataclass
from functools import partial

import anyio
import pytest

from app.runtime.scheduler_daemon import run_scheduler_daemon


@dataclass
class StubRuntime:
    started: int = 0
    stopped: int = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


@pytest.mark.anyio
async def test_scheduler_daemon_starts_runtime_and_waits_for_stop_signal():
    runtime = StubRuntime()
    stop_event = anyio.Event()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(
            partial(
                run_scheduler_daemon,
                runtime=runtime,
                stop_event=stop_event,
                idle_sleep_seconds=0.01,
            )
        )
        await anyio.sleep(0.02)
        assert runtime.started == 1
        assert runtime.stopped == 0
        stop_event.set()

    assert runtime.stopped == 1
