import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest
from app.infrastructure.db.models.jobs import QueuedJob
from app.infrastructure.db.models.systems import System
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.shared.enums import AssetStatus


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
async def test_submit_check_request_normalizes_defaults_and_falls_back_to_realtime_probe(
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
    assert plan.execution_track == "realtime_probe"

    assert job.job_type == "run_check"
    assert job.payload["execution_plan_id"] == str(result.plan_id)
    assert job.payload["execution_track"] == "realtime_probe"

    assert result.page_check_id is None
    assert result.execution_track == "realtime_probe"


@pytest.mark.anyio
async def test_submit_check_request_fails_when_check_falls_into_element_asset_missing_boundary(
    control_plane_service,
    seeded_asset_without_matching_check,
    db_session,
):
    with pytest.raises(HTTPException, match="element asset is missing"):
        await control_plane_service.submit_check_request(
            system_hint="WMS",
            page_hint="库存列表",
            check_goal="table_render",
        )

    assert db_session.exec(select(ExecutionPlan)).all() == []


@pytest.mark.anyio
async def test_submit_check_request_rolls_back_when_enqueue_fails(
    seeded_asset,
    db_session,
):
    class FailingDispatcher:
        async def enqueue(self, *, job_type: str, payload: dict[str, object]):
            raise RuntimeError("queue unavailable")

    service = ControlPlaneService(
        repository=SqlControlPlaneRepository(db_session),
        dispatcher=FailingDispatcher(),
    )

    with pytest.raises(RuntimeError, match="queue unavailable"):
        await service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="table_render",
        )

    assert db_session.exec(select(ExecutionRequest)).all() == []
    assert db_session.exec(select(ExecutionPlan)).all() == []
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_submit_check_request_prefers_safe_high_confidence_asset(
    db_session,
):
    system = System(
        code="oms",
        name="OMS",
        base_url="https://oms.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    ready_page = Page(
        system_id=system.id,
        route_path="/orders/ready",
        page_title="订单列表",
    )
    stale_page = Page(
        system_id=system.id,
        route_path="/orders/stale",
        page_title="订单列表",
    )
    db_session.add(ready_page)
    db_session.add(stale_page)
    db_session.flush()

    ready_asset = PageAsset(
        system_id=system.id,
        page_id=ready_page.id,
        asset_key="oms.orders.ready",
        asset_version="2026.04.02",
        status=AssetStatus.SAFE,
    )
    stale_asset = PageAsset(
        system_id=system.id,
        page_id=stale_page.id,
        asset_key="oms.orders.stale",
        asset_version="2026.04.03",
        status=AssetStatus.STALE,
    )
    db_session.add(ready_asset)
    db_session.add(stale_asset)
    db_session.flush()

    ready_check = PageCheck(
        page_asset_id=ready_asset.id,
        check_code="table_render",
        goal="table_render",
    )
    stale_check = PageCheck(
        page_asset_id=stale_asset.id,
        check_code="table_render",
        goal="table_render",
    )
    db_session.add(ready_check)
    db_session.add(stale_check)
    db_session.flush()

    db_session.add(
        IntentAlias(
            system_alias="OMS",
            page_alias="订单列表",
            check_alias="table_render",
            asset_key=stale_asset.asset_key,
            confidence=0.4,
            source="seed",
        )
    )
    db_session.add(
        IntentAlias(
            system_alias="OMS",
            page_alias="订单列表",
            check_alias="table_render",
            asset_key=ready_asset.asset_key,
            confidence=0.9,
            source="seed",
        )
    )
    db_session.commit()

    service = ControlPlaneService(
        repository=SqlControlPlaneRepository(db_session),
        dispatcher=SqlQueueDispatcher(db_session),
    )

    result = await service.submit_check_request(
        system_hint="OMS",
        page_hint="订单列表",
        check_goal="table_render",
    )

    plan = db_session.exec(select(ExecutionPlan)).one()
    assert plan.resolved_page_asset_id == ready_asset.id
    assert plan.resolved_page_check_id == ready_check.id
    assert result.page_check_id == ready_check.id


@pytest.mark.anyio
async def test_submit_check_request_uses_realtime_probe_when_page_or_menu_is_unresolved(
    control_plane_service,
    seeded_system,
    db_session,
):
    result = await control_plane_service.submit_check_request(
        system_hint="ERP",
        page_hint="不存在的页面",
        check_goal="page_open",
    )

    plan = db_session.exec(select(ExecutionPlan)).one()
    assert plan.resolved_system_id == seeded_system.id
    assert plan.resolved_page_asset_id is None
    assert plan.execution_track == "realtime_probe"
    assert result.execution_track == "realtime_probe"


@pytest.mark.anyio
async def test_submit_check_request_fails_when_page_is_resolved_but_element_asset_is_missing(
    control_plane_service,
    seeded_asset_without_matching_check,
):
    with pytest.raises(HTTPException, match="element asset is missing"):
        await control_plane_service.submit_check_request(
            system_hint="WMS",
            page_hint="库存列表",
            check_goal="table_render",
        )
