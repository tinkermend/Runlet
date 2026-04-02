from __future__ import annotations

from datetime import UTC, datetime

import anyio
import pytest
from sqlmodel import select

from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ScriptRender
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob


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
def scheduler_service(db_session):
    from app.domains.runner_service.scheduler import SchedulerService
    from app.infrastructure.queue.dispatcher import SqlQueueDispatcher

    return SchedulerService(
        session=db_session,
        dispatcher=SqlQueueDispatcher(db_session),
    )


@pytest.mark.anyio
async def test_scheduler_triggers_due_jobs(scheduler_service, seeded_published_job, db_session):
    fixed_now = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)
    scheduler_service.now_provider = lambda: fixed_now

    triggered = await scheduler_service.trigger_due_jobs()
    triggered_again = await scheduler_service.trigger_due_jobs()

    job_runs = db_session.exec(select(JobRun)).all()
    queued_jobs = db_session.exec(select(QueuedJob)).all()

    assert triggered == 1
    assert triggered_again == 0
    assert len(job_runs) == 1
    assert job_runs[0].scheduled_at.replace(tzinfo=UTC) == fixed_now
    assert any(job.job_type == "run_check" for job in queued_jobs)
    assert queued_jobs[0].payload["scheduled_at"] == fixed_now.isoformat()
