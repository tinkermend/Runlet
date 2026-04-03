from __future__ import annotations

import pytest
from sqlmodel import select

from app.domains.runner_service.schemas import PageProbePlan
from app.infrastructure.db.models.assets import IntentAlias
from app.infrastructure.db.models.crawl import Page
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRequest, ExecutionRun


class ProbeRuntime:
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

    async def open_create_modal(self) -> bool:
        return True

    async def capture_screenshot(self) -> bytes:
        return b"probe-screenshot"

    async def get_final_url(self) -> str:
        return "https://erp.example.com/unresolved"

    async def get_page_title(self) -> str:
        return "未解析页面"

    async def probe_page(self) -> dict[str, object]:
        return {
            "url": "https://erp.example.com/unresolved",
            "title": "未解析页面",
            "dialog_count": 0,
            "table_count": 0,
        }


@pytest.fixture
def realtime_probe_execution_plan_id(db_session, seeded_system):
    request = ExecutionRequest(
        request_source="worker_test",
        system_hint=seeded_system.code,
        page_hint="不存在的页面",
        check_goal="page_open",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(request)
    db_session.flush()

    plan = ExecutionPlan(
        execution_request_id=request.id,
        resolved_system_id=seeded_system.id,
        resolved_page_asset_id=None,
        resolved_page_check_id=None,
        execution_track="realtime_probe",
        auth_policy="server_injected",
        module_plan_id=None,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan.id


@pytest.fixture
def legacy_realtime_execution_plan_id(db_session, seeded_system):
    request = ExecutionRequest(
        request_source="worker_test",
        system_hint=seeded_system.code,
        page_hint="用户管理",
        check_goal="page_open",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(request)
    db_session.flush()

    plan = ExecutionPlan(
        execution_request_id=request.id,
        resolved_system_id=seeded_system.id,
        resolved_page_asset_id=None,
        resolved_page_check_id=None,
        execution_track="realtime",
        auth_policy="server_injected",
        module_plan_id=None,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan.id


@pytest.fixture
def realtime_probe_runner_service(db_session, seeded_auth_state):
    from app.domains.runner_service.service import RunnerService

    return RunnerService(session=db_session, runtime=ProbeRuntime())


@pytest.mark.anyio
async def test_realtime_probe_returns_failure_category_when_page_cannot_be_resolved(
    realtime_probe_runner_service,
    realtime_probe_execution_plan_id,
    db_session,
):
    result = await realtime_probe_runner_service.run_realtime_probe(
        execution_plan_id=realtime_probe_execution_plan_id,
    )

    execution_run = db_session.get(ExecutionRun, result.execution_run_id)

    assert result.status == "failed"
    assert result.page_check_id is None
    assert result.failure_category == "page_or_menu_not_resolved"
    assert execution_run is not None
    assert execution_run.failure_category == "page_or_menu_not_resolved"


@pytest.mark.anyio
async def test_realtime_probe_rejects_legacy_realtime_execution_track(
    realtime_probe_runner_service,
    legacy_realtime_execution_plan_id,
):
    with pytest.raises(ValueError, match="is not realtime_probe"):
        await realtime_probe_runner_service.run_realtime_probe(
            execution_plan_id=legacy_realtime_execution_plan_id,
        )


@pytest.mark.anyio
async def test_realtime_probe_builds_explicit_page_level_probe_plan(
    realtime_probe_runner_service,
):
    probe_plan = realtime_probe_runner_service._build_page_probe_plan(route_path="/users")

    assert isinstance(probe_plan, PageProbePlan)
    assert probe_plan.route_path == "/users"
    assert [step["module"] for step in probe_plan.steps_json] == [
        "auth.inject_state",
        "nav.menu_chain",
        "assert.page_open",
        "page.wait_ready",
    ]


@pytest.mark.anyio
async def test_successful_realtime_probe_writes_route_hint_alias(
    control_plane_service,
    realtime_probe_runner_service,
    realtime_probe_execution_plan_id,
    seeded_page_asset,
    db_session,
):
    plan = db_session.get(ExecutionPlan, realtime_probe_execution_plan_id)
    plan.resolved_page_asset_id = seeded_page_asset.id
    db_session.add(plan)
    db_session.commit()

    result = await realtime_probe_runner_service.run_realtime_probe(
        execution_plan_id=realtime_probe_execution_plan_id,
    )
    assert result.status == "passed"

    await control_plane_service.persist_realtime_probe_feedback(
        execution_plan_id=realtime_probe_execution_plan_id,
    )

    request = db_session.get(ExecutionRequest, plan.execution_request_id)
    page = db_session.get(Page, seeded_page_asset.page_id)

    alias = db_session.exec(
        select(IntentAlias)
        .where(IntentAlias.source == "realtime_probe")
        .where(IntentAlias.page_alias == request.page_hint)
        .where(IntentAlias.check_alias == request.check_goal)
    ).one()

    assert alias.system_alias == request.system_hint
    assert alias.page_alias == request.page_hint
    assert alias.route_hint == page.route_path
    assert alias.asset_key == seeded_page_asset.asset_key
    assert alias.source == "realtime_probe"


@pytest.mark.anyio
async def test_realtime_probe_marks_result_as_needs_recompile_when_probe_succeeds(
    realtime_probe_runner_service,
    realtime_probe_execution_plan_id,
    seeded_page_asset,
    db_session,
):
    plan = db_session.get(ExecutionPlan, realtime_probe_execution_plan_id)
    plan.resolved_page_asset_id = seeded_page_asset.id
    db_session.add(plan)
    db_session.commit()

    result = await realtime_probe_runner_service.run_realtime_probe(
        execution_plan_id=realtime_probe_execution_plan_id,
    )

    assert result.status == "passed"
    assert result.needs_recrawl is False
    assert result.needs_recompile is True
