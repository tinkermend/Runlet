from __future__ import annotations

from datetime import UTC, datetime, timedelta

import anyio
import pytest
from apscheduler.triggers.date import DateTrigger
from sqlmodel import Session
from sqlmodel import select

from app.domains.control_plane.scheduler_registry import (
    SchedulerRegistry,
    build_auth_policy_job_id,
    build_published_job_id,
)
from app.infrastructure.db.models.jobs import PublishedJob, QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy, SystemCrawlPolicy
from app.runtime.scheduler_runtime import SchedulerRuntime
from app.shared.enums import PublishedJobState, RuntimePolicyState


@pytest.fixture
def seeded_auth_policy(db_session, seeded_system):
    policy = SystemAuthPolicy(
        system_id=seeded_system.id,
        enabled=True,
        state=RuntimePolicyState.ACTIVE.value,
        schedule_expr="*/30 * * * *",
        auth_mode="slider_captcha",
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)
    return policy


@pytest.fixture
def scheduler_runtime(db_session, scheduler_registry):
    bind = db_session.bind

    def session_factory():
        return Session(bind=bind)

    return SchedulerRuntime(
        scheduler_registry=scheduler_registry,
        session_factory=session_factory,
    )


@pytest.mark.anyio
async def test_scheduler_runtime_restores_jobs_from_database(
    scheduler_runtime,
    seeded_published_job,
    seeded_auth_policy,
):
    await scheduler_runtime.start()
    try:
        assert scheduler_runtime.scheduler.get_job(build_published_job_id(seeded_published_job.id)) is not None
        assert scheduler_runtime.scheduler.get_job(build_auth_policy_job_id(seeded_auth_policy.system_id)) is not None
    finally:
        await scheduler_runtime.stop()


@pytest.mark.anyio
async def test_scheduler_runtime_reload_all_observes_external_database_updates(
    db_session,
    seeded_published_job,
    scheduler,
):
    bind = db_session.bind

    def session_factory():
        return Session(bind=bind)

    runtime = SchedulerRuntime(
        scheduler_registry=SchedulerRegistry(
            scheduler=scheduler,
            session_factory=session_factory,
        ),
        session_factory=session_factory,
    )

    await runtime.start()
    try:
        assert runtime.scheduler.get_job(build_published_job_id(seeded_published_job.id)) is not None

        with Session(bind=bind) as mutation_session:
            mutated_job = mutation_session.get(PublishedJob, seeded_published_job.id)
            assert mutated_job is not None
            mutated_job.state = PublishedJobState.PAUSED.value
            mutation_session.add(mutated_job)
            mutation_session.commit()

        await runtime.reload_all()

        assert runtime.scheduler.get_job(build_published_job_id(seeded_published_job.id)) is None
    finally:
        await runtime.stop()


@pytest.mark.anyio
async def test_published_job_callback_enqueues_once_per_minute(
    scheduler_runtime,
    seeded_published_job,
    db_session,
):
    fixed_now = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)

    await scheduler_runtime.start()
    try:
        first = await scheduler_runtime.trigger_published_job_now(
            seeded_published_job.id,
            scheduled_at=fixed_now,
        )
        second = await scheduler_runtime.trigger_published_job_now(
            seeded_published_job.id,
            scheduled_at=fixed_now,
        )
    finally:
        await scheduler_runtime.stop()

    queued_jobs = db_session.exec(select(QueuedJob).where(QueuedJob.job_type == "run_check")).all()

    assert first is True
    assert second is False
    assert len(queued_jobs) == 1


@pytest.mark.anyio
async def test_scheduler_runtime_uses_apscheduler_fire_time_for_published_callback(
    scheduler_runtime,
    seeded_published_job,
    db_session,
    monkeypatch,
):
    async def _no_reload() -> None:
        return None

    monkeypatch.setattr(scheduler_runtime.scheduler_registry, "load_all_from_db", _no_reload)
    monkeypatch.setattr(
        "app.runtime.scheduler_runtime.utcnow",
        lambda: datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
    )

    fire_time = (datetime.now(UTC) + timedelta(seconds=1)).replace(microsecond=0)

    await scheduler_runtime.start()
    try:
        scheduler_runtime.scheduler.add_job(
            lambda **_: None,
            trigger=DateTrigger(run_date=fire_time, timezone="UTC"),
            id=build_published_job_id(seeded_published_job.id),
            replace_existing=True,
            kwargs={
                "kind": "published_job",
                "entity_id": str(seeded_published_job.id),
            },
        )
        await _wait_for_run_check_queued_job(
            db_session=db_session,
            scheduled_at=fire_time.isoformat(),
        )
    finally:
        await scheduler_runtime.stop()

    queued_jobs = db_session.exec(select(QueuedJob).where(QueuedJob.job_type == "run_check")).all()
    matched = [job for job in queued_jobs if job.payload.get("scheduled_at") == fire_time.isoformat()]
    assert len(matched) == 1


def test_scheduler_runtime_callback_wrapper_uses_supplied_fire_time_for_auth_and_crawl(
    scheduler_runtime,
    seeded_auth_policy,
    db_session,
):
    crawl_policy = SystemCrawlPolicy(
        system_id=seeded_auth_policy.system_id,
        enabled=True,
        state=RuntimePolicyState.ACTIVE.value,
        schedule_expr="*/15 * * * *",
        crawl_scope="incremental",
    )
    db_session.add(crawl_policy)
    db_session.commit()
    db_session.refresh(crawl_policy)

    fire_time = datetime(2026, 4, 2, 9, 30, tzinfo=UTC)

    scheduler_runtime._dispatch_callback(
        kind="auth_policy",
        entity_id=str(seeded_auth_policy.id),
        scheduled_at=fire_time,
    )
    scheduler_runtime._dispatch_callback(
        kind="crawl_policy",
        entity_id=str(crawl_policy.id),
        scheduled_at=fire_time,
    )

    auth_jobs = db_session.exec(select(QueuedJob).where(QueuedJob.job_type == "auth_refresh")).all()
    crawl_jobs = db_session.exec(select(QueuedJob).where(QueuedJob.job_type == "crawl")).all()

    assert len(auth_jobs) == 1
    assert auth_jobs[0].policy_id == seeded_auth_policy.id
    assert auth_jobs[0].trigger_source == "scheduler"
    assert auth_jobs[0].scheduled_at.replace(tzinfo=UTC) == fire_time
    assert auth_jobs[0].payload["policy_id"] == str(seeded_auth_policy.id)
    assert auth_jobs[0].payload["trigger_source"] == "scheduler"
    assert auth_jobs[0].payload["scheduled_at"] == fire_time.isoformat()

    assert len(crawl_jobs) == 1
    assert crawl_jobs[0].policy_id == crawl_policy.id
    assert crawl_jobs[0].trigger_source == "scheduler"
    assert crawl_jobs[0].scheduled_at.replace(tzinfo=UTC) == fire_time
    assert crawl_jobs[0].payload["policy_id"] == str(crawl_policy.id)
    assert crawl_jobs[0].payload["trigger_source"] == "scheduler"
    assert crawl_jobs[0].payload["scheduled_at"] == fire_time.isoformat()


async def _wait_for_run_check_queued_job(*, db_session, scheduled_at: str, timeout_seconds: float = 3.0) -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
    while datetime.now(UTC) < deadline:
        queued_jobs = db_session.exec(select(QueuedJob).where(QueuedJob.job_type == "run_check")).all()
        if any(job.payload.get("scheduled_at") == scheduled_at for job in queued_jobs):
            return
        await anyio.sleep(0.05)
    raise AssertionError(f"timed out waiting for run_check queued job at {scheduled_at}")
