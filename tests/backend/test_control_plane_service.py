import pytest
from sqlmodel import select

from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest
from app.infrastructure.db.models.jobs import QueuedJob


@pytest.mark.anyio
async def test_submit_check_request_creates_request_plan_and_job(
    control_plane_service,
    seeded_asset,
    db_session,
):
    result = await control_plane_service.submit_check_request(
        system_hint="ERP",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
        request_source="skill",
    )

    request = db_session.exec(select(ExecutionRequest)).one()
    plan = db_session.exec(select(ExecutionPlan)).one()
    job = db_session.exec(select(QueuedJob)).one()

    assert request.system_hint == "ERP"
    assert request.page_hint == "用户管理"
    assert request.check_goal == "table_render"
    assert request.strictness == "balanced"
    assert request.time_budget_ms == 20_000
    assert request.request_source == "skill"

    assert plan.execution_request_id == result.request_id
    assert plan.resolved_page_asset_id == seeded_asset.id
    assert plan.resolved_page_check_id == result.page_check_id
    assert plan.execution_track == "precompiled"
    assert plan.auth_policy == "server_injected"

    assert job.id == result.job_id
    assert job.job_type == "run_check"
    assert job.payload["execution_plan_id"] == str(result.plan_id)
    assert job.payload["execution_track"] == "precompiled"

    assert result.execution_track == "precompiled"
    assert result.auth_policy == "server_injected"
    assert result.page_check_id is not None
    assert result.job_id is not None


@pytest.mark.anyio
async def test_submit_check_request_normalizes_defaults_and_falls_back_to_realtime(
    control_plane_service,
    db_session,
):
    result = await control_plane_service.submit_check_request(
        system_hint=" ERP ",
        check_goal="table_render",
    )

    request = db_session.exec(select(ExecutionRequest)).one()
    plan = db_session.exec(select(ExecutionPlan)).one()
    job = db_session.exec(select(QueuedJob)).one()

    assert request.system_hint == "ERP"
    assert request.page_hint is None
    assert request.strictness == "balanced"
    assert request.time_budget_ms == 20_000
    assert request.request_source == "api"

    assert plan.resolved_system_id is None
    assert plan.resolved_page_asset_id is None
    assert plan.resolved_page_check_id is None
    assert plan.execution_track == "realtime"

    assert job.job_type == "run_check"
    assert job.payload["execution_plan_id"] == str(result.plan_id)
    assert job.payload["execution_track"] == "realtime"

    assert result.page_check_id is None
    assert result.execution_track == "realtime"


@pytest.mark.anyio
async def test_submit_check_request_keeps_resolved_asset_when_check_falls_back_to_realtime(
    control_plane_service,
    seeded_asset_without_matching_check,
    db_session,
):
    result = await control_plane_service.submit_check_request(
        system_hint="WMS",
        page_hint="库存列表",
        check_goal="table_render",
    )

    plan = db_session.exec(select(ExecutionPlan)).one()

    assert plan.resolved_page_asset_id == seeded_asset_without_matching_check.id
    assert plan.resolved_page_check_id is None
    assert plan.execution_track == "realtime"

    assert result.page_check_id is None
    assert result.execution_track == "realtime"
    assert result.auth_policy == "server_injected"
