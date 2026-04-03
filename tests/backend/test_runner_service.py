from __future__ import annotations

from uuid import UUID

import pytest
from sqlmodel import select

from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ExecutionArtifact, ExecutionRun


@pytest.mark.anyio
async def test_run_page_check_result_includes_failure_category_and_page_context():
    from app.domains.runner_service.schemas import RunPageCheckResult

    assert "failure_category" in RunPageCheckResult.model_fields
    assert "final_url" in RunPageCheckResult.model_fields
    assert "page_title" in RunPageCheckResult.model_fields


@pytest.mark.anyio
async def test_execution_run_schema_exposes_failure_category_field():
    assert hasattr(ExecutionRun, "failure_category")


class FakeRuntime:
    def __init__(
        self,
        *,
        inject_outcome: bool = True,
        fail_action: str | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.inject_outcome = inject_outcome
        self.fail_action = fail_action

    async def inject_auth_state(self, *, storage_state: dict[str, object]) -> bool:
        self.calls.append({"action": "inject_auth_state", "storage_state": storage_state})
        return self.inject_outcome

    async def navigate_menu_chain(self, *, menu_chain: list[str], route_path: str) -> bool:
        self.calls.append(
            {
                "action": "navigate_menu_chain",
                "menu_chain": menu_chain,
                "route_path": route_path,
            }
        )
        if self.fail_action == "navigate_menu_chain":
            return False
        return True

    async def wait_page_ready(self, *, route_path: str) -> bool:
        self.calls.append({"action": "wait_page_ready", "route_path": route_path})
        if self.fail_action == "wait_page_ready":
            return False
        return True

    async def assert_table_visible(self, *, route_path: str | None = None) -> bool:
        self.calls.append({"action": "assert_table_visible", "route_path": route_path})
        if self.fail_action == "assert_table_visible":
            return False
        return True

    async def assert_page_open(self, *, route_path: str) -> bool:
        self.calls.append({"action": "assert_page_open", "route_path": route_path})
        if self.fail_action == "assert_page_open":
            return False
        return True


class LifecycleRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str | None = None
        self.closed = 0

    def set_base_url(self, base_url: str) -> None:
        self.base_url = base_url

    async def close(self) -> None:
        self.closed += 1


class FakeVisibleLocator:
    def __init__(self, *, count: int = 1) -> None:
        self._count = count
        self.wait_for_calls: list[dict[str, object]] = []

    @property
    def first(self) -> "FakeVisibleLocator":
        return self

    async def count(self) -> int:
        return self._count

    async def wait_for(self, *, state: str, timeout: int | None = None) -> None:
        self.wait_for_calls.append({"state": state, "timeout": timeout})


class FakeContainerLocator:
    def __init__(self, *, selector: str, count: int, role_locators: dict[tuple[str, str, bool], FakeVisibleLocator] | None = None) -> None:
        self.selector = selector
        self._count = count
        self.role_locators = role_locators or {}
        self.role_calls: list[dict[str, object]] = []

    async def count(self) -> int:
        return self._count

    def get_by_role(self, role: str, *, name: str, exact: bool = False) -> FakeVisibleLocator:
        self.role_calls.append({"role": role, "name": name, "exact": exact})
        return self.role_locators.get((role, name, exact), FakeVisibleLocator(count=0))


class FakePlaywrightPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.locator_calls: list[str] = []
        self.global_role_calls: list[dict[str, object]] = []
        self.menu_link = FakeVisibleLocator()
        self.locators = {
            "#menu_top_mix": FakeContainerLocator(
                selector="#menu_top_mix",
                count=1,
                role_locators={
                    ("link", "总览", True): self.menu_link,
                },
            ),
            "nav": FakeContainerLocator(selector="nav", count=0),
            "aside": FakeContainerLocator(selector="aside", count=0),
            "[role='menu']": FakeContainerLocator(selector="[role='menu']", count=0),
            "[role='navigation']": FakeContainerLocator(selector="[role='navigation']", count=0),
        }

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))

    def locator(self, selector: str) -> FakeContainerLocator:
        self.locator_calls.append(selector)
        return self.locators.get(selector, FakeContainerLocator(selector=selector, count=0))

    def get_by_role(self, role: str, *, name: str, exact: bool = False) -> FakeVisibleLocator:
        self.global_role_calls.append({"role": role, "name": name, "exact": exact})
        raise AssertionError("global get_by_role should not be used when scoped menu container exists")


class FakeGlobalFallbackPlaywrightPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.locator_calls: list[str] = []
        self.global_role_calls: list[dict[str, object]] = []
        self.global_menuitem = FakeVisibleLocator()

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))

    def locator(self, selector: str) -> FakeContainerLocator:
        self.locator_calls.append(selector)
        return FakeContainerLocator(selector=selector, count=0)

    def get_by_role(self, role: str, *, name: str, exact: bool = False) -> FakeVisibleLocator:
        self.global_role_calls.append({"role": role, "name": name, "exact": exact})
        if role == "link":
            return FakeVisibleLocator(count=0)
        if role == "menuitem":
            return self.global_menuitem
        return FakeVisibleLocator(count=0)


@pytest.fixture
def seeded_ready_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
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
    db_session.commit()
    db_session.refresh(seeded_page_check)
    return seeded_page_check


@pytest.fixture
def seeded_page_open_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
    module_plan = ModulePlan(
        page_asset_id=seeded_page_check.page_asset_id,
        check_code="page_open",
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {"module": "nav.menu_chain", "params": {"menu_chain": ["系统管理"], "route_path": "/users"}},
            {"module": "page.wait_ready", "params": {"route_path": "/users"}},
            {"module": "assert.page_ready", "params": {"route_path": "/users"}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    seeded_page_check.check_code = "page_open"
    seeded_page_check.goal = "page_open"
    seeded_page_check.module_plan_id = module_plan.id
    db_session.add(seeded_page_check)
    db_session.commit()
    db_session.refresh(seeded_page_check)
    return seeded_page_check


@pytest.fixture
def runner_service(db_session):
    from app.domains.runner_service.service import RunnerService

    return RunnerService(session=db_session, runtime=FakeRuntime())


@pytest.fixture
def failing_runner_service(db_session):
    from app.domains.runner_service.service import RunnerService

    return RunnerService(
        session=db_session,
        runtime=FakeRuntime(fail_action="assert_table_visible"),
    )


@pytest.fixture
def blocked_auth_runner_service(db_session):
    from app.domains.runner_service.service import RunnerService

    return RunnerService(
        session=db_session,
        runtime=FakeRuntime(inject_outcome=False),
    )


@pytest.fixture
def seeded_check_without_auth(db_session, seeded_page_check) -> PageCheck:
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


@pytest.mark.anyio
async def test_run_page_check_creates_execution_run_and_artifacts(runner_service, seeded_ready_check, db_session):
    result = await runner_service.run_page_check(page_check_id=seeded_ready_check.id)
    assert result.status in {"passed", "failed"}
    assert result.execution_run_id is not None

    execution_runs = db_session.exec(select(ExecutionRun)).all()
    artifacts = db_session.exec(select(ExecutionArtifact)).all()
    assert len(execution_runs) == 1
    assert execution_runs[0].id == result.execution_run_id
    assert len(artifacts) >= 1


@pytest.mark.anyio
async def test_run_page_check_uses_server_injected_auth(runner_service, seeded_ready_check):
    result = await runner_service.run_page_check(page_check_id=seeded_ready_check.id)
    assert result.auth_status in {"reused", "refreshed", "blocked"}


@pytest.mark.anyio
async def test_run_page_check_supports_assert_page_ready_alias(runner_service, seeded_page_open_check):
    result = await runner_service.run_page_check(page_check_id=seeded_page_open_check.id)
    assert result.status == "passed"
    assert result.execution_run_id is not None


@pytest.mark.anyio
async def test_run_page_check_configures_and_closes_runtime(db_session, seeded_ready_check, seeded_system):
    from app.domains.runner_service.service import RunnerService

    runtime = LifecycleRuntime()
    service = RunnerService(session=db_session, runtime=runtime)

    result = await service.run_page_check(page_check_id=seeded_ready_check.id)

    assert result.status == "passed"
    assert runtime.base_url == seeded_system.base_url
    assert runtime.closed == 1


@pytest.mark.anyio
async def test_run_page_check_raises_when_valid_auth_state_is_missing(
    db_session,
    seeded_check_without_auth,
):
    from app.domains.runner_service.service import RunnerService

    service = RunnerService(session=db_session, runtime=FakeRuntime())

    with pytest.raises(ValueError, match="valid auth state not found"):
        await service.run_page_check(page_check_id=seeded_check_without_auth.id)


@pytest.mark.anyio
async def test_run_page_check_persists_failed_execution_artifact(
    failing_runner_service,
    seeded_ready_check,
    db_session,
):
    result = await failing_runner_service.run_page_check(page_check_id=seeded_ready_check.id)

    execution_run = db_session.get(ExecutionRun, result.execution_run_id)
    artifacts = db_session.exec(select(ExecutionArtifact)).all()

    assert result.status == "failed"
    assert execution_run is not None
    assert execution_run.status == "failed"
    assert artifacts[-1].result_status.value == "failed"
    assert artifacts[-1].payload["step_results"][-1]["status"] == "failed"


@pytest.mark.anyio
async def test_run_page_check_fails_when_server_injected_auth_is_blocked(
    blocked_auth_runner_service,
    seeded_ready_check,
    db_session,
):
    result = await blocked_auth_runner_service.run_page_check(page_check_id=seeded_ready_check.id)

    execution_run = db_session.get(ExecutionRun, result.execution_run_id)
    artifact = db_session.exec(select(ExecutionArtifact)).all()[-1]

    assert result.status == "failed"
    assert result.auth_status == "blocked"
    assert execution_run is not None
    assert execution_run.status == "failed"
    assert artifact.result_status.value == "failed"
    assert artifact.payload["step_results"][0]["status"] == "failed"


@pytest.mark.anyio
async def test_playwright_runtime_prefers_scoped_menu_container_for_navigation():
    from app.domains.runner_service.playwright_runtime import PlaywrightRunnerRuntime

    runtime = PlaywrightRunnerRuntime()
    runtime.set_base_url("https://erp.example.com")
    runtime._page = FakePlaywrightPage()

    result = await runtime.navigate_menu_chain(
        menu_chain=["总览"],
        route_path="/front/database/allInstance",
    )

    assert result is True
    assert runtime._page.goto_calls == [
        ("https://erp.example.com/front/database/allInstance", "domcontentloaded")
    ]
    assert runtime._page.locator_calls[0] == "#menu_top_mix"
    assert runtime._page.menu_link.wait_for_calls == [{"state": "visible", "timeout": None}]
    assert runtime._page.global_role_calls == []


@pytest.mark.anyio
async def test_playwright_runtime_falls_back_to_global_menuitem_when_no_scoped_container_exists():
    from app.domains.runner_service.playwright_runtime import PlaywrightRunnerRuntime

    runtime = PlaywrightRunnerRuntime()
    runtime.set_base_url("https://erp.example.com")
    runtime._page = FakeGlobalFallbackPlaywrightPage()

    result = await runtime.navigate_menu_chain(
        menu_chain=["总览"],
        route_path="/front/database/allInstance",
    )

    assert result is True
    assert runtime._page.goto_calls == [
        ("https://erp.example.com/front/database/allInstance", "domcontentloaded")
    ]
    assert runtime._page.global_role_calls == [
        {"role": "link", "name": "总览", "exact": True},
        {"role": "menuitem", "name": "总览", "exact": True},
    ]
    assert runtime._page.global_menuitem.wait_for_calls == [{"state": "visible", "timeout": None}]
