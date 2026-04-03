from __future__ import annotations

import anyio
from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from app.domains.control_plane.job_types import RUN_CHECK_JOB_TYPE
from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest, ExecutionRun
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob
from app.shared.enums import AssetLifecycleStatus, PublishedJobState
from app.workers.runner import WorkerRunner


class FakeRuntime:
    async def inject_auth_state(self, *, storage_state: dict[str, object]) -> bool:
        return True

    async def navigate_menu_chain(self, *, menu_chain: list[str], route_path: str) -> bool:
        return True

    async def wait_page_ready(self, *, route_path: str) -> bool:
        return True

    async def assert_table_visible(self, *, route_path: str | None = None) -> bool:
        return True

    async def assert_page_open(self, *, route_path: str) -> bool:
        return True


class RetireBeforeRunnerService:
    def __init__(self, *, session):
        from app.domains.runner_service.service import RunnerService

        self._session = session
        self._delegate = RunnerService(session=session, runtime=FakeRuntime())

    async def run_page_check(self, *, page_check_id: UUID, execution_plan_id: UUID | None = None):
        target = self._session.get(PageCheck, page_check_id)
        assert target is not None
        target.lifecycle_status = AssetLifecycleStatus.RETIRED_REPLACED
        self._session.add(target)
        self._session.commit()
        self._session.refresh(target)
        return await self._delegate.run_page_check(
            page_check_id=page_check_id,
            execution_plan_id=execution_plan_id,
        )


@pytest.fixture
def seeded_run_check_target(db_session, seeded_page_check, seeded_page_asset, seeded_system, seeded_auth_state) -> PageCheck:
    module_plan = ModulePlan(
        page_asset_id=seeded_page_check.page_asset_id,
        check_code=seeded_page_check.check_code,
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {
                "module": "nav.menu_chain",
                "params": {"menu_chain": ["系统管理", "用户管理"], "route_path": "/users"},
            },
            {"module": "page.wait_ready", "params": {"route_path": "/users"}},
            {"module": "assert.table_visible", "params": {"route_path": "/users"}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    seeded_page_check.module_plan_id = module_plan.id
    db_session.add(seeded_page_check)

    execution_request = ExecutionRequest(
        request_source="worker_test",
        system_hint=seeded_system.code,
        page_hint=seeded_page_asset.asset_key,
        check_goal=seeded_page_check.goal,
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(execution_request)
    db_session.flush()

    execution_plan = ExecutionPlan(
        execution_request_id=execution_request.id,
        resolved_system_id=seeded_system.id,
        resolved_page_asset_id=seeded_page_asset.id,
        resolved_page_check_id=seeded_page_check.id,
        execution_track="precompiled",
        auth_policy="server_injected",
        module_plan_id=module_plan.id,
    )
    db_session.add(execution_plan)
    db_session.commit()
    db_session.refresh(seeded_page_check)
    return seeded_page_check


@pytest.fixture
def queued_run_check_job(db_session, seeded_run_check_target):
    execution_plan = db_session.exec(
        select(ExecutionPlan).where(ExecutionPlan.resolved_page_check_id == seeded_run_check_target.id)
    ).one()
    job = QueuedJob(
        job_type=RUN_CHECK_JOB_TYPE,
        payload={
            "execution_plan_id": str(execution_plan.id),
            "page_check_id": str(seeded_run_check_target.id),
            "execution_track": "precompiled",
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def retire_run_check_target(db_session, seeded_run_check_target):
    seeded_run_check_target.lifecycle_status = AssetLifecycleStatus.RETIRED_MISSING
    db_session.add(seeded_run_check_target)
    db_session.commit()
    db_session.refresh(seeded_run_check_target)
    return seeded_run_check_target


@pytest.fixture
def retire_run_check_target_replaced(db_session, seeded_run_check_target):
    seeded_run_check_target.lifecycle_status = AssetLifecycleStatus.RETIRED_REPLACED
    db_session.add(seeded_run_check_target)
    db_session.commit()
    db_session.refresh(seeded_run_check_target)
    return seeded_run_check_target


@pytest.fixture
def queued_invalid_run_check_job(db_session):
    job = QueuedJob(
        job_type=RUN_CHECK_JOB_TYPE,
        payload={"execution_plan_id": str(uuid4())},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def queued_realtime_run_check_job(db_session):
    job = QueuedJob(
        job_type=RUN_CHECK_JOB_TYPE,
        payload={
            "execution_request_id": str(uuid4()),
            "execution_plan_id": str(uuid4()),
            "execution_track": "realtime",
            "page_check_id": None,
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def seeded_published_job_for_run_check(db_session, seeded_run_check_target):
    from app.domains.runner_service.script_renderer import ScriptRenderer
    from app.infrastructure.db.models.execution import ScriptRender

    result = anyio.run(
        lambda: ScriptRenderer(session=db_session).render_page_check(
            page_check_id=seeded_run_check_target.id,
            render_mode="published",
        )
    )
    script_render = db_session.get(ScriptRender, result.script_render_id)
    assert script_render is not None

    published_job = PublishedJob(
        job_key="runner_worker_audit",
        page_check_id=seeded_run_check_target.id,
        script_render_id=script_render.id,
        asset_version=script_render.render_metadata["asset_version"],
        runtime_policy="published",
        schedule_expr="*/5 * * * *",
        state="active",
    )
    db_session.add(published_job)
    db_session.commit()
    db_session.refresh(published_job)
    return published_job


@pytest.fixture
def queued_published_run_check_job(db_session, seeded_published_job_for_run_check):
    job_run = JobRun(
        published_job_id=seeded_published_job_for_run_check.id,
        trigger_source="scheduler",
        run_status="accepted",
    )
    db_session.add(job_run)
    db_session.flush()

    job = QueuedJob(
        job_type=RUN_CHECK_JOB_TYPE,
        payload={
            "page_check_id": str(seeded_published_job_for_run_check.page_check_id),
            "execution_track": "precompiled",
            "published_job_id": str(seeded_published_job_for_run_check.id),
            "job_run_id": str(job_run.id),
            "script_render_id": str(seeded_published_job_for_run_check.script_render_id),
            "asset_version": seeded_published_job_for_run_check.asset_version,
            "runtime_policy": seeded_published_job_for_run_check.runtime_policy,
            "schedule_expr": seeded_published_job_for_run_check.schedule_expr,
            "trigger_source": "scheduler",
            "scheduled_at": "2026-04-02T08:00:00+00:00",
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    db_session.refresh(job_run)
    return job


@pytest.fixture
def queued_mismatched_published_run_check_job(db_session, seeded_published_job_for_run_check):
    other_job = PublishedJob(
        job_key="runner_worker_audit_mismatch",
        page_check_id=seeded_published_job_for_run_check.page_check_id,
        script_render_id=seeded_published_job_for_run_check.script_render_id,
        asset_version=seeded_published_job_for_run_check.asset_version,
        runtime_policy=seeded_published_job_for_run_check.runtime_policy,
        schedule_expr="*/10 * * * *",
        state="active",
    )
    db_session.add(other_job)
    db_session.flush()

    job_run = JobRun(
        published_job_id=seeded_published_job_for_run_check.id,
        trigger_source="scheduler",
        run_status="accepted",
    )
    db_session.add(job_run)
    db_session.flush()

    job = QueuedJob(
        job_type=RUN_CHECK_JOB_TYPE,
        payload={
            "page_check_id": str(seeded_published_job_for_run_check.page_check_id),
            "execution_track": "precompiled",
            "published_job_id": str(other_job.id),
            "job_run_id": str(job_run.id),
        },
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def job_runner(db_session):
    from app.domains.runner_service.service import RunnerService
    from app.jobs.run_check_job import RunCheckJobHandler

    runner_service = RunnerService(session=db_session, runtime=FakeRuntime())
    return WorkerRunner(
        session=db_session,
        handlers={
            RUN_CHECK_JOB_TYPE: RunCheckJobHandler(
                session=db_session,
                runner_service=runner_service,
            )
        },
    )


@pytest.fixture
def job_runner_with_race_retirement(db_session):
    from app.jobs.run_check_job import RunCheckJobHandler

    runner_service = RetireBeforeRunnerService(session=db_session)
    return WorkerRunner(
        session=db_session,
        handlers={
            RUN_CHECK_JOB_TYPE: RunCheckJobHandler(
                session=db_session,
                runner_service=runner_service,
            )
        },
    )


@pytest.fixture
def pause_linked_published_job_for_retirement(db_session, seeded_published_job_for_run_check):
    seeded_published_job_for_run_check.state = PublishedJobState.PAUSED
    seeded_published_job_for_run_check.pause_reason = "asset_retired_replaced"
    seeded_published_job_for_run_check.paused_by_page_check_id = seeded_published_job_for_run_check.page_check_id
    db_session.add(seeded_published_job_for_run_check)
    db_session.commit()
    db_session.refresh(seeded_published_job_for_run_check)
    return seeded_published_job_for_run_check


@pytest.fixture
def pause_linked_published_job_without_retirement_markers(db_session, seeded_published_job_for_run_check):
    seeded_published_job_for_run_check.state = PublishedJobState.PAUSED
    seeded_published_job_for_run_check.pause_reason = "asset_retired_replaced"
    seeded_published_job_for_run_check.paused_by_snapshot_id = None
    seeded_published_job_for_run_check.paused_by_asset_id = None
    seeded_published_job_for_run_check.paused_by_page_check_id = None
    db_session.add(seeded_published_job_for_run_check)
    db_session.commit()
    db_session.refresh(seeded_published_job_for_run_check)
    return seeded_published_job_for_run_check


@pytest.mark.anyio
async def test_run_check_job_creates_execution_run(job_runner, queued_run_check_job, db_session):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_run_check_job.id)
    execution_run = db_session.exec(select(ExecutionRun).order_by(ExecutionRun.id.desc())).first()

    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.result_payload is not None
    assert refreshed.result_payload["status"] == "passed"
    assert execution_run is not None


@pytest.mark.anyio
async def test_run_check_job_skips_when_target_was_retired_after_enqueue(
    job_runner,
    queued_run_check_job,
    retire_run_check_target,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "skipped"
    assert refreshed.failure_message == "asset_retired_missing"


@pytest.mark.anyio
async def test_run_check_job_skips_for_retired_replaced_target_with_fixed_failure_message(
    job_runner,
    queued_run_check_job,
    retire_run_check_target_replaced,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "skipped"
    assert refreshed.failure_message == "asset_retired_missing"


@pytest.mark.anyio
async def test_run_check_job_skips_when_linked_published_job_paused_by_retired_reason(
    job_runner,
    queued_published_run_check_job,
    pause_linked_published_job_for_retirement,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_published_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "skipped"
    assert refreshed.failure_message == "asset_retired_missing"

    job_run = db_session.get(JobRun, UUID(refreshed.payload["job_run_id"]))
    assert job_run is not None
    assert job_run.run_status == "skipped"
    assert job_run.failure_message == "asset_retired_missing"


@pytest.mark.anyio
async def test_run_check_job_does_not_skip_when_linked_published_job_paused_without_retired_markers(
    job_runner,
    queued_published_run_check_job,
    pause_linked_published_job_without_retirement_markers,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_published_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.failure_message is None


@pytest.mark.anyio
async def test_run_check_job_skips_when_target_retired_between_handler_guard_and_runner_execution(
    job_runner_with_race_retirement,
    queued_run_check_job,
    db_session,
):
    await job_runner_with_race_retirement.run_once()

    refreshed = db_session.get(QueuedJob, queued_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "skipped"
    assert refreshed.failure_message == "asset_retired_missing"


@pytest.mark.anyio
async def test_run_check_job_marks_queue_item_failed_when_payload_is_missing_page_check_id(
    job_runner,
    queued_invalid_run_check_job,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_invalid_run_check_job.id)

    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.failure_message == "missing page_check_id in run_check job payload"


@pytest.mark.anyio
async def test_run_check_job_skips_realtime_request_without_resolved_page_check(
    job_runner,
    queued_realtime_run_check_job,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_realtime_run_check_job.id)

    assert refreshed is not None
    assert refreshed.status == "skipped"
    assert refreshed.failure_message == "realtime execution track is not supported by run_check worker"
    assert refreshed.result_payload["queued_job_id"] == str(queued_realtime_run_check_job.id)
    assert refreshed.result_payload["execution_track"] == "realtime"


@pytest.mark.anyio
async def test_run_check_job_persists_audit_context_for_published_job(
    job_runner,
    queued_published_run_check_job,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_published_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.result_payload is not None
    assert refreshed.result_payload["queued_job_id"] == str(refreshed.id)
    assert refreshed.result_payload["published_job_id"] == refreshed.payload["published_job_id"]
    assert refreshed.result_payload["job_run_id"] == refreshed.payload["job_run_id"]
    assert refreshed.result_payload["script_render_id"] == refreshed.payload["script_render_id"]
    assert refreshed.result_payload["asset_version"] == refreshed.payload["asset_version"]
    assert refreshed.result_payload["runtime_policy"] == refreshed.payload["runtime_policy"]
    assert refreshed.result_payload["schedule_expr"] == refreshed.payload["schedule_expr"]
    assert refreshed.result_payload["trigger_source"] == refreshed.payload["trigger_source"]

    job_run = db_session.get(JobRun, UUID(refreshed.result_payload["job_run_id"]))
    assert job_run is not None
    assert job_run.execution_run_id is not None


@pytest.mark.anyio
async def test_run_check_job_fails_when_published_job_linkage_mismatches(
    job_runner,
    queued_mismatched_published_run_check_job,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_mismatched_published_run_check_job.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.failure_message == "published_job_id does not match job_run linkage"

    job_run_id = UUID(refreshed.payload["job_run_id"])
    job_run = db_session.get(JobRun, job_run_id)
    assert job_run is not None
    assert job_run.run_status == "failed"
    assert job_run.failure_message == refreshed.failure_message
