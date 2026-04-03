from __future__ import annotations

from uuid import UUID

import pytest
from sqlmodel import select

from app.domains.runner_service.failure_categories import FailureCategory
from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ExecutionArtifact, ExecutionRun
from pydantic.fields import PydanticUndefined


@pytest.mark.anyio
async def test_run_page_check_result_fields_match_failure_category_contract():
    from app.domains.runner_service.schemas import RunPageCheckResult

    fields = RunPageCheckResult.model_fields
    failure_field = fields["failure_category"]
    screenshot_artifact_ids_field = fields["screenshot_artifact_ids"]
    final_url_field = fields["final_url"]
    page_title_field = fields["page_title"]

    assert failure_field.annotation == FailureCategory | None
    assert failure_field.default is None

    assert screenshot_artifact_ids_field.annotation == list[UUID]

    assert final_url_field.annotation == str | None
    assert final_url_field.default is None

    assert page_title_field.annotation == str | None
    assert page_title_field.default is None


@pytest.mark.anyio
async def test_execution_run_failure_category_field_stays_string_backed():
    field = ExecutionRun.model_fields["failure_category"]
    assert field.annotation == str | None
    assert field.sa_column is PydanticUndefined
    assert any(getattr(metadata, "max_length", None) == 64 for metadata in field.metadata)


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
        self.final_url = "https://erp.example.com/users"
        self.page_title = "用户管理"
        self.screenshot_bytes = b"fake-screenshot-png"
        self.probe_payload: dict[str, object] = {
            "url": self.final_url,
            "title": self.page_title,
        }

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

    async def open_create_modal(self) -> bool:
        self.calls.append({"action": "open_create_modal"})
        if self.fail_action == "open_create_modal":
            return False
        return True

    async def capture_screenshot(self) -> bytes:
        self.calls.append({"action": "capture_screenshot"})
        return self.screenshot_bytes

    async def get_final_url(self) -> str | None:
        self.calls.append({"action": "get_final_url"})
        return self.final_url

    async def get_page_title(self) -> str | None:
        self.calls.append({"action": "get_page_title"})
        return self.page_title

    async def probe_page(self) -> dict[str, object]:
        self.calls.append({"action": "probe_page"})
        return self.probe_payload


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


class FakeRuntimeContextPage:
    def __init__(self) -> None:
        self.url = "https://erp.example.com/users?tab=list"
        self.title_calls = 0
        self.screenshot_calls: list[dict[str, object]] = []

    async def screenshot(self, *, full_page: bool, type: str) -> bytes:
        self.screenshot_calls.append({"full_page": full_page, "type": type})
        return b"\x89PNG\r\nfake"

    async def title(self) -> str:
        self.title_calls += 1
        return "用户管理"


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
def seeded_open_create_modal_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
    module_plan = ModulePlan(
        page_asset_id=seeded_page_check.page_asset_id,
        check_code="open_create_modal",
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {"module": "nav.menu_chain", "params": {"menu_chain": ["系统管理"], "route_path": "/users"}},
            {"module": "page.wait_ready", "params": {"route_path": "/users"}},
            {"module": "action.open_create_modal", "params": {}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    seeded_page_check.check_code = "open_create_modal"
    seeded_page_check.goal = "open_create_modal"
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
async def test_run_page_check_persists_screenshot_and_final_page_context(
    runner_service,
    seeded_ready_check,
    db_session,
):
    result = await runner_service.run_page_check(page_check_id=seeded_ready_check.id)
    artifacts = db_session.exec(
        select(ExecutionArtifact).where(ExecutionArtifact.execution_run_id == result.execution_run_id)
    ).all()
    screenshot_artifacts = [artifact for artifact in artifacts if artifact.artifact_kind == "screenshot"]

    assert result.final_url
    assert result.page_title is not None
    assert screenshot_artifacts
    assert screenshot_artifacts[0].payload["mime_type"] == "image/png"
    assert screenshot_artifacts[0].payload["content"]
    assert screenshot_artifacts[0].payload["final_url"] == result.final_url
    assert set(result.artifact_ids) == {artifact.id for artifact in artifacts}
    assert set(result.screenshot_artifact_ids) == {artifact.id for artifact in screenshot_artifacts}


@pytest.mark.anyio
async def test_run_page_check_supports_open_create_modal(
    runner_service,
    seeded_open_create_modal_check,
):
    result = await runner_service.run_page_check(page_check_id=seeded_open_create_modal_check.id)
    assert result.status == "passed"


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
    artifacts = db_session.exec(
        select(ExecutionArtifact).where(ExecutionArtifact.execution_run_id == result.execution_run_id)
    ).all()
    module_artifact = next(artifact for artifact in artifacts if artifact.artifact_kind == "module_execution")

    assert result.status == "failed"
    assert result.failure_category == FailureCategory.ASSERTION_FAILED
    assert execution_run is not None
    assert execution_run.status == "failed"
    assert execution_run.failure_category == FailureCategory.ASSERTION_FAILED.value
    assert execution_run.duration_ms is not None
    assert execution_run.duration_ms >= 0
    assert module_artifact.result_status.value == "failed"
    assert module_artifact.payload["step_results"][-1]["status"] == "failed"


@pytest.mark.anyio
async def test_run_page_check_fails_when_server_injected_auth_is_blocked(
    blocked_auth_runner_service,
    seeded_ready_check,
    db_session,
):
    result = await blocked_auth_runner_service.run_page_check(page_check_id=seeded_ready_check.id)

    execution_run = db_session.get(ExecutionRun, result.execution_run_id)
    artifacts = db_session.exec(
        select(ExecutionArtifact).where(ExecutionArtifact.execution_run_id == result.execution_run_id)
    ).all()
    module_artifact = next(artifact for artifact in artifacts if artifact.artifact_kind == "module_execution")

    assert result.status == "failed"
    assert result.auth_status == "blocked"
    assert result.failure_category == FailureCategory.AUTH_BLOCKED
    assert execution_run is not None
    assert execution_run.status == "failed"
    assert execution_run.failure_category == FailureCategory.AUTH_BLOCKED.value
    assert module_artifact.result_status.value == "failed"
    assert module_artifact.payload["step_results"][0]["status"] == "failed"


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


@pytest.mark.anyio
async def test_playwright_runtime_exposes_page_context_and_screenshot_methods():
    from app.domains.runner_service.playwright_runtime import PlaywrightRunnerRuntime

    runtime = PlaywrightRunnerRuntime()
    runtime._page = FakeRuntimeContextPage()

    screenshot = await runtime.capture_screenshot()
    final_url = await runtime.get_final_url()
    page_title = await runtime.get_page_title()

    assert screenshot == b"\x89PNG\r\nfake"
    assert runtime._page.screenshot_calls == [{"full_page": True, "type": "png"}]
    assert final_url == "https://erp.example.com/users?tab=list"
    assert page_title == "用户管理"
    assert runtime._page.title_calls == 1
