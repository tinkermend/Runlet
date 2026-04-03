import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.domains.control_plane.repository import SqlControlPlaneRepository
from app.domains.control_plane.service import ControlPlaneService
from app.domains.runner_service.scheduler import PublishedJobService
from app.infrastructure.db.models.assets import IntentAlias, PageAsset, PageCheck
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest
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
