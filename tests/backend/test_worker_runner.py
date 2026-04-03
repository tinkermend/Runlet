from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anyio
import pytest

from app.config.settings import settings
from app.domains.auth_service.schemas import AuthRefreshResult
from app.domains.control_plane.job_types import (
    AUTH_REFRESH_JOB_TYPE,
    ASSET_COMPILE_JOB_TYPE,
    CRAWL_JOB_TYPE,
    RUN_CHECK_JOB_TYPE,
)
from app.domains.crawler_service.schemas import CrawlRunResult
from app.infrastructure.db.models.jobs import QueuedJob, utcnow
from app.jobs.auth_refresh_job import AuthRefreshJobHandler
from app.jobs.crawl_job import CrawlJobHandler
from app.shared.enums import QueuedJobStatus
from app.workers import runner as worker_runner_module
from app.workers.runner import WorkerRunner, build_worker_handlers


class StubAuthService:
    def __init__(self, result: AuthRefreshResult) -> None:
        self.result = result
        self.calls = []

    async def refresh_auth_state(self, *, system_id):
        self.calls.append(system_id)
        return self.result


class ExplodingHandler:
    async def run(self, *, job_id):
        raise RuntimeError(f"boom for {job_id}")


class StubCrawlerService:
    def __init__(self, result: CrawlRunResult) -> None:
        self.result = result
        self.calls = []

    async def run_crawl(self, *, system_id, crawl_scope: str) -> CrawlRunResult:
        self.calls.append({"system_id": system_id, "crawl_scope": crawl_scope})
        return self.result


def _create_auth_job(db_session, *, system_id, created_at) -> QueuedJob:
    job = QueuedJob(
        job_type=AUTH_REFRESH_JOB_TYPE,
        payload={"system_id": str(system_id)},
        created_at=created_at,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.mark.anyio
async def test_worker_runner_fetches_accepted_jobs_in_fifo_order(
    db_session,
    seeded_system,
):
    older_job = _create_auth_job(
        db_session,
        system_id=seeded_system.id,
        created_at=utcnow() - timedelta(minutes=5),
    )
    newer_job = _create_auth_job(
        db_session,
        system_id=seeded_system.id,
        created_at=utcnow() - timedelta(minutes=1),
    )
    auth_service = StubAuthService(
        AuthRefreshResult(
            system_id=seeded_system.id,
            status="success",
            auth_state_id=uuid4(),
        )
    )
    job_runner = WorkerRunner(
        session=db_session,
        handlers={
            AUTH_REFRESH_JOB_TYPE: AuthRefreshJobHandler(
                session=db_session,
                auth_service=auth_service,
            )
        },
    )

    await job_runner.run_once()

    first = db_session.get(QueuedJob, older_job.id)
    second = db_session.get(QueuedJob, newer_job.id)
    assert first is not None and second is not None
    assert first.status == QueuedJobStatus.COMPLETED.value
    assert second.status == QueuedJobStatus.ACCEPTED.value
    assert auth_service.calls == [seeded_system.id]


@pytest.mark.anyio
async def test_worker_runner_marks_unhandled_job_as_skipped_with_reason(
    db_session,
):
    job = QueuedJob(
        job_type=ASSET_COMPILE_JOB_TYPE,
        payload={"snapshot_id": str(uuid4())},
        created_at=utcnow(),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    job_runner = WorkerRunner(session=db_session, handlers={})

    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    assert refreshed is not None
    assert refreshed.status == QueuedJobStatus.SKIPPED.value
    assert refreshed.failure_message == "no handler registered for job type: asset_compile"


def test_build_worker_handlers_registers_run_check_handler(db_session):
    handlers = build_worker_handlers(
        session=db_session,
        runner_service=object(),
    )

    assert RUN_CHECK_JOB_TYPE in handlers


def test_build_worker_handlers_wires_control_plane_into_asset_compile_handler(db_session):
    class StubControlPlaneService:
        async def apply_reconciliation_cascades(self, **kwargs):
            return None

    handlers = build_worker_handlers(
        session=db_session,
        asset_compiler_service=object(),
        control_plane_service=StubControlPlaneService(),
    )

    handler = handlers[ASSET_COMPILE_JOB_TYPE]
    assert getattr(handler, "control_plane_service") is not None


@pytest.mark.anyio
async def test_worker_runner_marks_job_failed_when_handler_raises(
    db_session,
):
    job = QueuedJob(
        job_type=ASSET_COMPILE_JOB_TYPE,
        payload={"snapshot_id": str(uuid4())},
        created_at=utcnow(),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    job_runner = WorkerRunner(
        session=db_session,
        handlers={ASSET_COMPILE_JOB_TYPE: ExplodingHandler()},
    )

    handled = await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    assert handled is True
    assert refreshed is not None
    assert refreshed.status == QueuedJobStatus.FAILED.value
    assert refreshed.failure_message.startswith("handler crashed: boom for")


@pytest.mark.anyio
async def test_worker_runner_run_forever_stops_on_signal(db_session):
    runner = WorkerRunner(session=db_session, handlers={})
    stop_event = anyio.Event()
    calls = {"count": 0}

    async def fake_run_once() -> bool:
        calls["count"] += 1
        return False

    runner.run_once = fake_run_once  # type: ignore[assignment]

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(runner.run_forever, 5, stop_event)
        await anyio.sleep(0.02)
        stop_event.set()

    assert calls["count"] > 0


@pytest.mark.anyio
async def test_worker_runner_persists_auth_policy_trigger_audit_fields(
    db_session,
    seeded_system,
):
    scheduled_at = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)
    policy_id = uuid4()
    job = QueuedJob(
        job_type=AUTH_REFRESH_JOB_TYPE,
        payload={
            "system_id": str(seeded_system.id),
            "policy_id": str(policy_id),
            "trigger_source": "scheduler",
            "scheduled_at": scheduled_at.isoformat(),
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    auth_service = StubAuthService(
        AuthRefreshResult(
            system_id=seeded_system.id,
            status="success",
            auth_state_id=uuid4(),
        )
    )
    runner = WorkerRunner(
        session=db_session,
        handlers={
            AUTH_REFRESH_JOB_TYPE: AuthRefreshJobHandler(
                session=db_session,
                auth_service=auth_service,
            )
        },
    )

    await runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    assert refreshed is not None
    assert refreshed.policy_id == policy_id
    assert refreshed.trigger_source == "scheduler"
    assert refreshed.scheduled_at.replace(tzinfo=UTC) == scheduled_at


@pytest.mark.anyio
async def test_worker_runner_persists_crawl_policy_trigger_audit_fields(
    db_session,
    seeded_system,
):
    scheduled_at = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)
    policy_id = uuid4()
    job = QueuedJob(
        job_type=CRAWL_JOB_TYPE,
        payload={
            "system_id": str(seeded_system.id),
            "crawl_scope": "incremental",
            "policy_id": str(policy_id),
            "trigger_source": "scheduler",
            "scheduled_at": scheduled_at.isoformat(),
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    crawler_service = StubCrawlerService(
        CrawlRunResult(
            system_id=seeded_system.id,
            status="success",
            snapshot_id=uuid4(),
            pages_saved=1,
        )
    )
    runner = WorkerRunner(
        session=db_session,
        handlers={
            CRAWL_JOB_TYPE: CrawlJobHandler(
                session=db_session,
                crawler_service=crawler_service,
            )
        },
    )

    await runner.run_once()

    refreshed = db_session.get(QueuedJob, job.id)
    assert refreshed is not None
    assert refreshed.policy_id == policy_id
    assert refreshed.trigger_source == "scheduler"
    assert refreshed.scheduled_at.replace(tzinfo=UTC) == scheduled_at


@pytest.mark.anyio
async def test_worker_runner_run_forever_uses_configured_poll_interval_when_not_overridden(
    db_session,
    monkeypatch,
):
    runner = WorkerRunner(session=db_session, handlers={})
    stop_event = anyio.Event()
    calls = {"count": 0}
    sleep_seconds: list[float] = []

    async def fake_run_once() -> bool:
        calls["count"] += 1
        return False

    async def fake_sleep(seconds: float) -> None:
        sleep_seconds.append(seconds)
        stop_event.set()

    runner.run_once = fake_run_once  # type: ignore[assignment]
    monkeypatch.setattr(settings, "worker_poll_interval_ms", 7)
    monkeypatch.setattr("app.workers.runner.anyio.sleep", fake_sleep)

    await runner.run_forever(stop_event=stop_event, poll_interval_ms=None)

    assert calls["count"] > 0
    assert sleep_seconds == [0.007]


@pytest.mark.anyio
async def test_run_worker_process_builds_runner_and_runs_forever(monkeypatch):
    captured: dict[str, object] = {}

    class StubProcessRunner:
        async def run_forever(
            self,
            poll_interval_ms: int | None = None,
            stop_event: anyio.Event | None = None,
        ) -> None:
            captured["poll_interval_ms"] = poll_interval_ms
            captured["stop_event"] = stop_event

    def fake_build_worker_runner():
        captured["built"] = True
        return StubProcessRunner()

    monkeypatch.setattr(
        worker_runner_module,
        "build_worker_runner",
        fake_build_worker_runner,
    )

    stop_event = anyio.Event()
    await worker_runner_module.run_worker_process(
        stop_event=stop_event,
        poll_interval_ms=123,
    )

    assert captured == {
        "built": True,
        "poll_interval_ms": 123,
        "stop_event": stop_event,
    }


def test_build_worker_runner_wires_default_handlers(monkeypatch):
    fake_session = object()

    class StubSessionFactory:
        def __call__(self):
            return fake_session

    monkeypatch.setattr(
        worker_runner_module,
        "create_session_factory",
        lambda: StubSessionFactory(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "AuthService",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "CrawlerService",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "AssetCompilerService",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "RunnerService",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "PlaywrightBrowserLoginAdapter",
        lambda: object(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "PlaywrightBrowserFactory",
        lambda: object(),
    )
    monkeypatch.setattr(
        worker_runner_module,
        "PlaywrightRunnerRuntime",
        lambda: object(),
    )

    runner = worker_runner_module.build_worker_runner()

    assert runner.session is fake_session
    assert set(runner.handlers) == {
        AUTH_REFRESH_JOB_TYPE,
        CRAWL_JOB_TYPE,
        ASSET_COMPILE_JOB_TYPE,
        RUN_CHECK_JOB_TYPE,
    }
