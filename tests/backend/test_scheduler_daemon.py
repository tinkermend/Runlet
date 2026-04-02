from __future__ import annotations

from dataclasses import dataclass
from functools import partial

import anyio
import pytest

from app.api import deps as api_deps
from app.runtime import scheduler_daemon as scheduler_daemon_module
from app.runtime.scheduler_daemon import run_scheduler_daemon


@dataclass
class StubRuntime:
    started: int = 0
    stopped: int = 0
    reloaded: int = 0

    async def start(self) -> None:
        self.started += 1

    async def reload_all(self) -> None:
        self.reloaded += 1

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


@pytest.mark.anyio
async def test_scheduler_daemon_periodically_reloads_runtime():
    runtime = StubRuntime()
    stop_event = anyio.Event()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(
            partial(
                run_scheduler_daemon,
                runtime=runtime,
                stop_event=stop_event,
                idle_sleep_seconds=0.01,
                reload_interval_seconds=0.01,
            )
        )
        await anyio.sleep(0.035)
        stop_event.set()

    assert runtime.started == 1
    assert runtime.reloaded >= 2
    assert runtime.stopped == 1


@pytest.mark.anyio
async def test_run_scheduler_process_builds_runtime_and_runs_daemon(monkeypatch):
    runtime = StubRuntime()
    captured: dict[str, object] = {}

    def fake_build_scheduler_runtime():
        return runtime

    async def fake_run_scheduler_daemon(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        scheduler_daemon_module,
        "build_scheduler_runtime",
        fake_build_scheduler_runtime,
    )
    monkeypatch.setattr(
        scheduler_daemon_module,
        "run_scheduler_daemon",
        fake_run_scheduler_daemon,
    )

    stop_event = anyio.Event()
    await scheduler_daemon_module.run_scheduler_process(
        stop_event=stop_event,
        idle_sleep_seconds=0.25,
        reload_interval_seconds=5.0,
    )

    assert captured["runtime"] is runtime
    assert captured["stop_event"] is stop_event
    assert captured["idle_sleep_seconds"] == 0.25
    assert captured["reload_interval_seconds"] == 5.0


def test_registry_scheduler_uses_configured_timezone(monkeypatch):
    previous_scheduler = api_deps._registry_scheduler
    if previous_scheduler is not None and previous_scheduler.running:
        previous_scheduler.shutdown(wait=False)
    api_deps._registry_scheduler = None
    monkeypatch.setattr(api_deps.settings, "scheduler_timezone", "Asia/Shanghai")

    scheduler = api_deps.get_registry_scheduler()
    try:
        assert str(scheduler.timezone) == "Asia/Shanghai"
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        api_deps._registry_scheduler = None
