from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel import select

from app.domains.control_plane.scheduler_registry import build_auth_policy_job_id, build_published_job_id
from app.domains.runner_service.scheduler import PublishedJobService
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.runtime_policies import SystemAuthPolicy
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.runtime.scheduler_runtime import SchedulerRuntime
from app.shared.enums import RuntimePolicyState


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
    dispatcher = SqlQueueDispatcher(db_session)
    return SchedulerRuntime(
        session=db_session,
        scheduler_registry=scheduler_registry,
        published_job_service=PublishedJobService(
            session=db_session,
            dispatcher=dispatcher,
        ),
        dispatcher=dispatcher,
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
