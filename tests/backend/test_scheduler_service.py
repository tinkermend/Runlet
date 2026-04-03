from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest
from sqlmodel import select

from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ScriptRender
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob


def test_published_job_service_no_longer_exposes_bulk_cron_scanner():
    from app.domains.runner_service.scheduler import PublishedJobService

    assert not hasattr(PublishedJobService, "trigger_due_jobs")


def test_runner_scheduler_module_no_longer_exposes_legacy_scheduler_service():
    from app.domains.runner_service import scheduler as scheduler_module

    assert not hasattr(scheduler_module, "SchedulerService")


@pytest.fixture
def seeded_schedulable_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
    module_plan = ModulePlan(
        page_asset_id=seeded_page_check.page_asset_id,
        check_code=seeded_page_check.check_code,
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {"module": "page.wait_ready", "params": {"route_path": "/users"}},
            {"module": "assert.table_visible", "params": {"route_path": "/users"}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    seeded_page_check.module_plan_id = module_plan.id
    db_session.add(seeded_page_check)
    db_session.commit()
    db_session.refresh(seeded_page_check)
    return seeded_page_check


@pytest.fixture
def seeded_published_job(db_session, seeded_schedulable_check):
    from app.domains.runner_service.script_renderer import ScriptRenderer

    render_result = anyio.run(
        lambda: ScriptRenderer(session=db_session).render_page_check(
            page_check_id=seeded_schedulable_check.id,
            render_mode="published",
        )
    )
    script_render = db_session.get(ScriptRender, render_result.script_render_id)
    assert script_render is not None

    published_job = PublishedJob(
        job_key="erp_users_table_render",
        page_check_id=seeded_schedulable_check.id,
        script_render_id=script_render.id,
        asset_version=script_render.render_metadata["asset_version"],
        runtime_policy="published",
        schedule_expr="* * * * *",
        state="active",
    )
    db_session.add(published_job)
    db_session.commit()
    db_session.refresh(published_job)
    return published_job


@pytest.fixture
def published_job_service(db_session):
    from app.domains.runner_service.scheduler import PublishedJobService
    from app.infrastructure.queue.dispatcher import SqlQueueDispatcher

    return PublishedJobService(
        session=db_session,
        dispatcher=SqlQueueDispatcher(db_session),
    )


@pytest.mark.anyio
async def test_published_job_service_triggers_single_job_once_per_minute(
    published_job_service,
    seeded_published_job,
    db_session,
):
    fixed_now = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)

    first = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=fixed_now,
    )
    second = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=fixed_now,
    )

    job_runs = db_session.exec(select(JobRun)).all()
    queued_jobs = db_session.exec(select(QueuedJob)).all()

    assert first is True
    assert second is False
    assert len(job_runs) == 1
    assert job_runs[0].scheduled_at.replace(tzinfo=UTC) == fixed_now
    assert any(job.job_type == "run_check" for job in queued_jobs)
    assert queued_jobs[0].trigger_source == "scheduler"
    assert queued_jobs[0].scheduled_at.replace(tzinfo=UTC) == fixed_now
    assert queued_jobs[0].payload["scheduled_at"] == fixed_now.isoformat()


@pytest.mark.anyio
async def test_published_job_service_skips_stale_schedule_fire(
    published_job_service,
    seeded_published_job,
    db_session,
):
    seeded_published_job.schedule_expr = "0 */2 * * *"
    db_session.add(seeded_published_job)
    db_session.commit()
    db_session.refresh(seeded_published_job)

    triggered = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=datetime(2026, 4, 2, 8, 1, tzinfo=UTC),
    )

    assert triggered is False
    assert db_session.exec(select(JobRun)).all() == []
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_published_job_service_skips_paused_job(
    published_job_service,
    seeded_published_job,
    db_session,
):
    seeded_published_job.state = "paused"
    db_session.add(seeded_published_job)
    db_session.commit()
    db_session.refresh(seeded_published_job)

    triggered = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
    )

    assert triggered is False
    assert db_session.exec(select(JobRun)).all() == []
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_published_job_service_skips_day_of_month_mismatch(
    published_job_service,
    seeded_published_job,
    db_session,
):
    seeded_published_job.schedule_expr = "0 8 3 * *"
    db_session.add(seeded_published_job)
    db_session.commit()
    db_session.refresh(seeded_published_job)

    triggered = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
    )

    assert triggered is False
    assert db_session.exec(select(JobRun)).all() == []
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_published_job_service_skips_weekday_mismatch(
    published_job_service,
    seeded_published_job,
    db_session,
):
    seeded_published_job.schedule_expr = "0 8 * * 5"
    db_session.add(seeded_published_job)
    db_session.commit()
    db_session.refresh(seeded_published_job)

    triggered = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
    )

    assert triggered is False
    assert db_session.exec(select(JobRun)).all() == []
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_published_job_service_matches_cron_weekday_mapping(
    published_job_service,
    seeded_published_job,
    db_session,
):
    seeded_published_job.schedule_expr = "0 8 * * 4"
    db_session.add(seeded_published_job)
    db_session.commit()
    db_session.refresh(seeded_published_job)

    triggered = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
    )

    assert triggered is True
    assert len(db_session.exec(select(JobRun)).all()) == 1
    assert len(db_session.exec(select(QueuedJob)).all()) == 1


@pytest.mark.anyio
async def test_pause_jobs_for_retired_page_check_marks_published_jobs_paused(
    published_job_service,
    seeded_published_job,
    seeded_snapshot,
    db_session,
):
    paused = await published_job_service.pause_jobs_for_retired_page_check(
        page_check_id=seeded_published_job.page_check_id,
        snapshot_id=seeded_snapshot.id,
        reason="asset_retired_missing",
    )

    db_session.refresh(seeded_published_job)
    assert paused == 1
    assert seeded_published_job.state == "paused"
    assert seeded_published_job.pause_reason == "asset_retired_missing"
    assert seeded_published_job.paused_by_snapshot_id == seeded_snapshot.id
    assert seeded_published_job.paused_by_page_check_id == seeded_published_job.page_check_id
