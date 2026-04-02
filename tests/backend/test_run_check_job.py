from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import select

from app.domains.control_plane.job_types import RUN_CHECK_JOB_TYPE
from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest, ExecutionRun
from app.infrastructure.db.models.jobs import QueuedJob
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
