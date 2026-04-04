from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.domains.runner_service.scheduler import PublishedJobService
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest, ExecutionRun
from app.infrastructure.db.models.jobs import PublishedJob, QueuedJob
from app.infrastructure.db.models.systems import System
from app.infrastructure.queue.dispatcher import SqlQueueDispatcher
from app.shared.enums import AssetLifecycleStatus, AssetStatus


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
async def test_submit_check_request_persists_template_metadata(
    control_plane_service,
    seeded_asset,
    db_session,
):
    template_context = {
        "template_code": "field_equals_exists",
        "template_version": "v1",
        "carrier_hint": "table",
        "template_params": {
            "field": "username",
            "operator": "equals",
            "value": "alice",
        },
    }

    result = await control_plane_service.submit_check_request(
        system_hint="ERP",
        page_hint="用户管理",
        check_goal="table_render",
        **template_context,
    )

    request = db_session.exec(
        select(ExecutionRequest).where(ExecutionRequest.id == result.request_id)
    ).one()
    assert request.template_code == template_context["template_code"]
    assert request.template_version == template_context["template_version"]
    assert request.carrier_hint == template_context["carrier_hint"]
    assert request.template_params == template_context["template_params"]


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


@pytest.mark.anyio
async def test_submit_check_request_rejects_non_readonly_template_action(control_plane_service):
    with pytest.raises(HTTPException, match="readonly template required"):
        await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="delete_resource",
            template_code="delete_resource",
            template_version="v1",
            carrier_hint="table",
            template_params={"field": "username", "operator": "equals", "value": "alice"},
        )


@pytest.mark.anyio
async def test_submit_check_request_returns_element_asset_missing_for_template_when_page_resolved(
    control_plane_service,
    seeded_asset_without_matching_check,
):
    with pytest.raises(HTTPException, match="element asset is missing"):
        await control_plane_service.submit_check_request(
            system_hint="WMS",
            page_hint="库存列表",
            check_goal="field_equals_exists",
            template_code="field_equals_exists",
            template_version="v1",
            carrier_hint="table",
            template_params={"field": "username", "operator": "equals", "value": "alice"},
        )


@pytest.mark.anyio
async def test_get_check_request_status_normalizes_legacy_realtime_track(
    control_plane_service,
    accepted_request,
    db_session,
):
    plan = db_session.get(ExecutionPlan, accepted_request.plan_id)
    assert plan is not None
    plan.execution_track = "realtime"
    db_session.add(plan)
    db_session.commit()

    status = await control_plane_service.get_check_request_status(accepted_request.request_id)
    assert status.execution_track == "realtime_probe"


@pytest.mark.anyio
async def test_submit_check_request_ignores_disabled_alias_and_retired_asset(
    control_plane_service,
    seeded_asset,
    seeded_page_check,
    db_session,
):
    alias = db_session.exec(
        select(IntentAlias).where(IntentAlias.asset_key == seeded_asset.asset_key)
    ).one()
    alias.is_active = False
    alias.disabled_reason = "retired_missing"
    seeded_asset.lifecycle_status = AssetLifecycleStatus.RETIRED_MISSING
    seeded_page_check.lifecycle_status = AssetLifecycleStatus.RETIRED_MISSING
    db_session.add(alias)
    db_session.add(seeded_asset)
    db_session.add(seeded_page_check)
    db_session.commit()

    with pytest.raises(HTTPException, match="asset is retired") as exc_info:
        await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="table_render",
        )

    assert exc_info.value.status_code == 409
    assert db_session.exec(select(ExecutionRequest)).all() == []
    assert db_session.exec(select(ExecutionPlan)).all() == []
    assert db_session.exec(select(QueuedJob)).all() == []


@pytest.mark.anyio
async def test_apply_reconciliation_cascades_disables_aliases_and_pauses_published_jobs(
    control_plane_service,
    seeded_asset,
    seeded_page_check,
    seeded_snapshot,
    seeded_published_job,
    db_session,
):
    alias = db_session.exec(
        select(IntentAlias).where(IntentAlias.asset_key == seeded_asset.asset_key)
    ).one()

    result = await control_plane_service.apply_reconciliation_cascades(
        snapshot_id=seeded_snapshot.id,
        alias_ids_to_disable=[alias.id],
        alias_ids_to_enable=[],
        published_job_ids_to_pause=[seeded_published_job.id],
        published_job_ids_to_resume=[],
        alias_disable_decision_count=1,
        alias_enable_decision_count=0,
        published_job_pause_decision_count=1,
        published_job_resume_decision_count=0,
    )

    db_session.refresh(alias)
    db_session.refresh(seeded_published_job)

    assert result.alias_disable_decision_count == 1
    assert result.alias_enable_decision_count == 0
    assert result.published_job_pause_decision_count == 1
    assert result.published_job_resume_decision_count == 0
    assert result.aliases_disabled == 1
    assert result.aliases_enabled == 0
    assert result.published_jobs_paused == 1
    assert result.published_jobs_resumed == 0

    assert alias.is_active is False
    assert alias.disabled_reason == "retired_missing"
    assert alias.disabled_by_snapshot_id == seeded_snapshot.id
    assert seeded_published_job.state == "paused"
    assert seeded_published_job.pause_reason == "asset_retired_missing"
    assert seeded_published_job.paused_by_snapshot_id == seeded_snapshot.id
    assert seeded_published_job.paused_by_page_check_id == seeded_page_check.id


@pytest.mark.anyio
async def test_apply_reconciliation_cascades_enables_aliases_and_resumes_published_jobs(
    control_plane_service,
    seeded_asset,
    seeded_page_check,
    seeded_snapshot,
    seeded_published_job,
    db_session,
):
    alias = db_session.exec(
        select(IntentAlias).where(IntentAlias.asset_key == seeded_asset.asset_key)
    ).one()
    alias.is_active = False
    alias.disabled_reason = "retired_missing"
    alias.disabled_by_snapshot_id = seeded_snapshot.id
    seeded_published_job.state = "paused"
    seeded_published_job.pause_reason = "asset_retired_missing"
    seeded_published_job.paused_by_snapshot_id = seeded_snapshot.id
    seeded_published_job.paused_by_page_check_id = seeded_page_check.id
    db_session.add(alias)
    db_session.add(seeded_published_job)
    db_session.commit()

    result = await control_plane_service.apply_reconciliation_cascades(
        snapshot_id=seeded_snapshot.id,
        alias_ids_to_disable=[],
        alias_ids_to_enable=[alias.id],
        published_job_ids_to_pause=[],
        published_job_ids_to_resume=[seeded_published_job.id],
        alias_disable_decision_count=0,
        alias_enable_decision_count=1,
        published_job_pause_decision_count=0,
        published_job_resume_decision_count=1,
    )

    db_session.refresh(alias)
    db_session.refresh(seeded_published_job)

    assert result.alias_disable_decision_count == 0
    assert result.alias_enable_decision_count == 1
    assert result.published_job_pause_decision_count == 0
    assert result.published_job_resume_decision_count == 1
    assert result.aliases_disabled == 0
    assert result.aliases_enabled == 1
    assert result.published_jobs_paused == 0
    assert result.published_jobs_resumed == 1
    assert alias.is_active is True
    assert alias.disabled_reason is None
    assert alias.disabled_by_snapshot_id is None
    assert seeded_published_job.state == "active"
    assert seeded_published_job.pause_reason is None
    assert seeded_published_job.paused_by_snapshot_id is None
    assert seeded_published_job.paused_by_page_check_id is None


@pytest.mark.anyio
async def test_apply_reconciliation_cascades_rolls_back_when_pause_fails(
    seeded_asset,
    seeded_page_check,
    seeded_snapshot,
    seeded_published_job,
    db_session,
):
    alias = db_session.exec(
        select(IntentAlias).where(IntentAlias.asset_key == seeded_asset.asset_key)
    ).one()

    class FailingPublishedJobService(PublishedJobService):
        async def pause_published_jobs_by_ids(
            self,
            *,
            published_job_ids,
            snapshot_id,
            reason,
            commit=True,
        ) -> int:
            raise RuntimeError("pause failure")

    dispatcher = SqlQueueDispatcher(db_session)
    service = ControlPlaneService(
        repository=SqlControlPlaneRepository(db_session),
        dispatcher=dispatcher,
        published_job_service=FailingPublishedJobService(session=db_session, dispatcher=dispatcher),
    )

    with pytest.raises(RuntimeError, match="pause failure"):
        await service.apply_reconciliation_cascades(
            snapshot_id=seeded_snapshot.id,
            alias_ids_to_disable=[alias.id],
            alias_ids_to_enable=[],
            published_job_ids_to_pause=[seeded_published_job.id],
            published_job_ids_to_resume=[],
            alias_disable_decision_count=1,
            alias_enable_decision_count=0,
            published_job_pause_decision_count=1,
            published_job_resume_decision_count=0,
        )

    db_session.refresh(alias)
    db_session.refresh(seeded_published_job)
    assert alias.is_active is True
    assert alias.disabled_reason is None
    assert seeded_published_job.state == "active"


@pytest.mark.anyio
async def test_get_check_candidates_cold_start_prefers_alias_confidence(
    control_plane_service,
    db_session,
):
    system = System(
        code="erp",
        name="ERP",
        base_url="https://erp.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    page_a = Page(system_id=system.id, route_path="/users/a", page_title="用户管理")
    page_b = Page(system_id=system.id, route_path="/users/b", page_title="用户管理")
    db_session.add(page_a)
    db_session.add(page_b)
    db_session.flush()

    asset_a = PageAsset(
        system_id=system.id,
        page_id=page_a.id,
        asset_key="erp.users.a",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    asset_b = PageAsset(
        system_id=system.id,
        page_id=page_b.id,
        asset_key="erp.users.b",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    db_session.add(asset_a)
    db_session.add(asset_b)
    db_session.flush()

    check_a = PageCheck(page_asset_id=asset_a.id, check_code="table_render", goal="table_render")
    check_b = PageCheck(page_asset_id=asset_b.id, check_code="table_render", goal="table_render")
    db_session.add(check_a)
    db_session.add(check_b)
    db_session.flush()

    alias_a = IntentAlias(
        system_alias="ERP",
        page_alias="用户管理",
        check_alias="table_render",
        asset_key=asset_a.asset_key,
        confidence=0.9,
        source="seed",
    )
    alias_b = IntentAlias(
        system_alias="ERP",
        page_alias="用户管理",
        check_alias="table_render",
        asset_key=asset_b.asset_key,
        confidence=0.2,
        source="seed",
    )
    db_session.add(alias_a)
    db_session.add(alias_b)
    db_session.commit()

    result = await control_plane_service.get_check_candidates(
        system_hint="ERP",
        page_hint="用户管理",
        intent="查询用户",
    )

    assert result.candidates
    assert result.candidates[0].page_check_id == check_a.id


@pytest.mark.anyio
async def test_get_check_candidates_weighted_prefers_success_rate(
    control_plane_service,
    db_session,
):
    system = System(
        code="crm",
        name="CRM",
        base_url="https://crm.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    page_a = Page(system_id=system.id, route_path="/users/a", page_title="用户管理")
    page_b = Page(system_id=system.id, route_path="/users/b", page_title="用户管理")
    db_session.add(page_a)
    db_session.add(page_b)
    db_session.flush()

    asset_a = PageAsset(
        system_id=system.id,
        page_id=page_a.id,
        asset_key="crm.users.a",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    asset_b = PageAsset(
        system_id=system.id,
        page_id=page_b.id,
        asset_key="crm.users.b",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    db_session.add(asset_a)
    db_session.add(asset_b)
    db_session.flush()

    check_a = PageCheck(
        page_asset_id=asset_a.id,
        check_code="table_render",
        goal="table_render",
        success_rate=0.9,
    )
    check_b = PageCheck(
        page_asset_id=asset_b.id,
        check_code="table_render",
        goal="table_render",
        success_rate=0.2,
    )
    db_session.add(check_a)
    db_session.add(check_b)
    db_session.flush()

    alias_a = IntentAlias(
        system_alias="CRM",
        page_alias="用户管理",
        check_alias="table_render",
        asset_key=asset_a.asset_key,
        confidence=0.5,
        source="seed",
    )
    alias_b = IntentAlias(
        system_alias="CRM",
        page_alias="用户管理",
        check_alias="table_render",
        asset_key=asset_b.asset_key,
        confidence=0.5,
        source="seed",
    )
    db_session.add(alias_a)
    db_session.add(alias_b)
    db_session.flush()

    request_a = ExecutionRequest(
        request_source="api",
        system_hint="CRM",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    request_b = ExecutionRequest(
        request_source="api",
        system_hint="CRM",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(request_a)
    db_session.add(request_b)
    db_session.flush()

    plan_a = ExecutionPlan(
        execution_request_id=request_a.id,
        resolved_system_id=system.id,
        resolved_page_asset_id=asset_a.id,
        resolved_page_check_id=check_a.id,
        execution_track="precompiled",
        auth_policy="server_injected",
    )
    plan_b = ExecutionPlan(
        execution_request_id=request_b.id,
        resolved_system_id=system.id,
        resolved_page_asset_id=asset_b.id,
        resolved_page_check_id=check_b.id,
        execution_track="precompiled",
        auth_policy="server_injected",
    )
    db_session.add(plan_a)
    db_session.add(plan_b)
    db_session.flush()

    now = datetime.now(timezone.utc)
    for index in range(20):
        db_session.add(
            ExecutionRun(
                execution_plan_id=plan_a.id,
                status="passed",
                created_at=now - timedelta(days=2, seconds=index),
            )
        )
        db_session.add(
            ExecutionRun(
                execution_plan_id=plan_b.id,
                status="passed",
                created_at=now - timedelta(days=1, seconds=index),
            )
        )
    db_session.commit()

    result = await control_plane_service.get_check_candidates(
        system_hint="CRM",
        page_hint="用户管理",
        intent="查询用户",
    )

    assert result.candidates
    assert result.candidates[0].page_check_id == check_a.id


@pytest.mark.anyio
async def test_get_check_candidates_applies_cold_start_per_candidate(
    control_plane_service,
    db_session,
):
    system = System(
        code="mix",
        name="MIX",
        base_url="https://mix.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    page_warm = Page(system_id=system.id, route_path="/users/warm", page_title="用户管理")
    page_cold = Page(system_id=system.id, route_path="/users/cold", page_title="用户管理")
    db_session.add(page_warm)
    db_session.add(page_cold)
    db_session.flush()

    asset_warm = PageAsset(
        system_id=system.id,
        page_id=page_warm.id,
        asset_key="mix.users.warm",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    asset_cold = PageAsset(
        system_id=system.id,
        page_id=page_cold.id,
        asset_key="mix.users.cold",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    db_session.add(asset_warm)
    db_session.add(asset_cold)
    db_session.flush()

    check_warm = PageCheck(
        page_asset_id=asset_warm.id,
        check_code="table_render",
        goal="table_render",
        success_rate=1.0,
    )
    check_cold = PageCheck(
        page_asset_id=asset_cold.id,
        check_code="table_render",
        goal="table_render",
        success_rate=0.1,
    )
    db_session.add(check_warm)
    db_session.add(check_cold)
    db_session.flush()

    db_session.add(
        IntentAlias(
            system_alias="MIX",
            page_alias="用户管理",
            check_alias="table_render",
            asset_key=asset_warm.asset_key,
            confidence=0.2,
            source="seed",
        )
    )
    db_session.add(
        IntentAlias(
            system_alias="MIX",
            page_alias="用户管理",
            check_alias="table_render",
            asset_key=asset_cold.asset_key,
            confidence=0.8,
            source="seed",
        )
    )
    db_session.flush()

    request_warm = ExecutionRequest(
        request_source="api",
        system_hint="MIX",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    request_cold = ExecutionRequest(
        request_source="api",
        system_hint="MIX",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(request_warm)
    db_session.add(request_cold)
    db_session.flush()

    plan_warm = ExecutionPlan(
        execution_request_id=request_warm.id,
        resolved_system_id=system.id,
        resolved_page_asset_id=asset_warm.id,
        resolved_page_check_id=check_warm.id,
        execution_track="precompiled",
        auth_policy="server_injected",
    )
    plan_cold = ExecutionPlan(
        execution_request_id=request_cold.id,
        resolved_system_id=system.id,
        resolved_page_asset_id=asset_cold.id,
        resolved_page_check_id=check_cold.id,
        execution_track="precompiled",
        auth_policy="server_injected",
    )
    db_session.add(plan_warm)
    db_session.add(plan_cold)
    db_session.flush()

    now = datetime.now(timezone.utc)
    for index in range(20):
        db_session.add(
            ExecutionRun(
                execution_plan_id=plan_warm.id,
                status="passed",
                created_at=now - timedelta(seconds=index),
            )
        )
    db_session.add(
        ExecutionRun(
            execution_plan_id=plan_cold.id,
            status="passed",
            created_at=now - timedelta(days=1),
        )
    )
    db_session.commit()

    result = await control_plane_service.get_check_candidates(
        system_hint="MIX",
        page_hint="用户管理",
        intent="查询用户",
    )

    assert len(result.candidates) >= 2
    assert result.candidates[0].page_check_id == check_warm.id
    assert result.candidates[0].rank_score > result.candidates[1].rank_score


@pytest.mark.anyio
async def test_get_check_candidates_cold_start_breaks_tie_with_recency(
    control_plane_service,
    db_session,
):
    system = System(
        code="cold",
        name="COLD",
        base_url="https://cold.example.com",
        framework_type="react",
    )
    db_session.add(system)
    db_session.flush()

    page_new = Page(system_id=system.id, route_path="/users/new", page_title="用户管理")
    page_old = Page(system_id=system.id, route_path="/users/old", page_title="用户管理")
    db_session.add(page_new)
    db_session.add(page_old)
    db_session.flush()

    asset_new = PageAsset(
        system_id=system.id,
        page_id=page_new.id,
        asset_key="cold.users.new",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    asset_old = PageAsset(
        system_id=system.id,
        page_id=page_old.id,
        asset_key="cold.users.old",
        asset_version="2026.04.01",
        status=AssetStatus.SAFE,
    )
    db_session.add(asset_new)
    db_session.add(asset_old)
    db_session.flush()

    check_new = PageCheck(page_asset_id=asset_new.id, check_code="table_render", goal="table_render")
    check_old = PageCheck(page_asset_id=asset_old.id, check_code="table_render", goal="table_render")
    db_session.add(check_new)
    db_session.add(check_old)
    db_session.flush()

    db_session.add(
        IntentAlias(
            system_alias="COLD",
            page_alias="用户管理",
            check_alias="table_render",
            asset_key=asset_new.asset_key,
            confidence=0.8,
            source="seed",
        )
    )
    db_session.add(
        IntentAlias(
            system_alias="COLD",
            page_alias="用户管理",
            check_alias="table_render",
            asset_key=asset_old.asset_key,
            confidence=0.8,
            source="seed",
        )
    )
    db_session.flush()

    request_new = ExecutionRequest(
        request_source="api",
        system_hint="COLD",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    request_old = ExecutionRequest(
        request_source="api",
        system_hint="COLD",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(request_new)
    db_session.add(request_old)
    db_session.flush()

    plan_new = ExecutionPlan(
        execution_request_id=request_new.id,
        resolved_system_id=system.id,
        resolved_page_asset_id=asset_new.id,
        resolved_page_check_id=check_new.id,
        execution_track="precompiled",
        auth_policy="server_injected",
    )
    plan_old = ExecutionPlan(
        execution_request_id=request_old.id,
        resolved_system_id=system.id,
        resolved_page_asset_id=asset_old.id,
        resolved_page_check_id=check_old.id,
        execution_track="precompiled",
        auth_policy="server_injected",
    )
    db_session.add(plan_new)
    db_session.add(plan_old)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        ExecutionRun(
            execution_plan_id=plan_new.id,
            status="passed",
            created_at=now,
        )
    )
    db_session.add(
        ExecutionRun(
            execution_plan_id=plan_old.id,
            status="passed",
            created_at=now - timedelta(days=2),
        )
    )
    db_session.commit()

    result = await control_plane_service.get_check_candidates(
        system_hint="COLD",
        page_hint="用户管理",
        intent="查询用户",
    )

    assert len(result.candidates) >= 2
    assert result.candidates[0].page_check_id == check_new.id
    assert result.candidates[0].rank_score == pytest.approx(result.candidates[1].rank_score)
