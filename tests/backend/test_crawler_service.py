import sys
from types import ModuleType
from urllib.parse import urlparse

import pytest
from sqlmodel import select

from app.domains.crawler_service.schemas import (
    CrawlExtractionResult,
    ElementCandidate,
    MenuCandidate,
    PageCandidate,
)
from app.domains.crawler_service.extractors.dom_menu import DomMenuTraversalExtractor
from app.domains.crawler_service.service import CrawlerService, PlaywrightBrowserFactory
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement


def test_page_element_schema_exposes_state_and_locator_candidates():
    assert "state_signature" in ElementCandidate.model_fields
    assert "state_context" in ElementCandidate.model_fields
    assert "locator_candidates" in ElementCandidate.model_fields


class FakeBrowserSession:
    def __init__(self) -> None:
        self.closed = False
        self.route_hints: list[dict[str, object]] = []
        self.dom_menu_nodes: list[dict[str, object]] = []
        self.dom_elements: list[dict[str, object]] = []
        self.raise_route_hint_error = False

    async def close(self) -> None:
        self.closed = True

    async def collect_route_hints(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        if self.raise_route_hint_error:
            raise RuntimeError("route hints unavailable")
        return self.route_hints

    async def collect_dom_menu_nodes(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return self.dom_menu_nodes

    async def collect_dom_elements(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return self.dom_elements


class FakeBrowserFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.session = FakeBrowserSession()

    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
    ) -> FakeBrowserSession:
        self.calls.append({"base_url": base_url, "storage_state": storage_state})
        return self.session


class FakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.route_snapshot_eval_calls = 0
        self.readiness_shell_eval_calls = 0
        self.fail_content_probe = False

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str):
        if "document.readyState" in script and "shell_ready" in script:
            self.readiness_shell_eval_calls += 1
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            if self.fail_content_probe:
                raise RuntimeError("content probe failed")
            return self.settled
        if not self.settled:
            if "__RUNLET_ROUTE_SNAPSHOT__" in script:
                self.route_snapshot_eval_calls += 1
                parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
                return {
                    "pathname": parsed.path or "/",
                    "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                    "router_route": None,
                    "history_route": None,
                }
            if "__RUNLET_ROUTE_HINTS__" in script:
                return [{"path": "/", "title": "加载中"}]
            if "__RUNLET_MENU_NODES__" in script:
                return []
            if "__RUNLET_PAGE_ELEMENTS__" in script:
                return []
            if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
                return []
            if "__RUNLET_NETWORK_RESOURCES__" in script:
                return []
            if "__RUNLET_NETWORK_REQUESTS__" in script:
                return []
            if "__RUNLET_PAGE_METADATA__" in script:
                return []
        if "__RUNLET_ROUTE_HINTS__" in script:
            assert "__NEXT_DATA__" in script
            assert "__NUXT__" in script
            assert "__VUE_ROUTER__" in script
            return [
                {"path": "/dashboard", "title": "仪表盘"},
                {"path": "/users", "title": "用户管理"},
            ]
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            self.route_snapshot_eval_calls += 1
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": "/users" if parsed.path == "/users" else None,
                "history_route": None,
            }
        if "__RUNLET_MENU_NODES__" in script:
            return [
                {"label": "仪表盘", "route_path": "/dashboard", "role": "menuitem"},
                {"label": "用户管理", "route_path": "/users", "role": "menuitem"},
            ]
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            return [
                {
                    "page_route_path": "/dashboard",
                    "element_type": "button",
                    "role": "button",
                    "text": "刷新",
                }
            ]
        if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
            return [{"route_path": "/reports", "source": "runtime_route_manifest"}]
        if "__RUNLET_NETWORK_RESOURCES__" in script:
            return [{"route_path": "/users", "source": "network_resource"}]
        if "__RUNLET_NETWORK_REQUESTS__" in script:
            return [{"path": "/dashboard", "source": "network_request"}]
        if "__RUNLET_PAGE_METADATA__" in script:
            if self.current_url.endswith("/users"):
                return [
                    {"route_path": "/users", "page_title": "用户管理", "reachable": True, "status_code": 200},
                ]
            if self.current_url.endswith("/dashboard"):
                return [
                    {"route_path": "/dashboard", "page_title": "仪表盘", "reachable": True, "status_code": 200},
                ]
            return [{"route_path": "/", "page_title": "首页", "reachable": True, "status_code": 200}]
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


class FakeCrawlerContext:
    def __init__(self, page: FakeCrawlerPage) -> None:
        self.page = page
        self.closed = False

    async def new_page(self) -> FakeCrawlerPage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeCrawlerBrowser:
    def __init__(self, context: FakeCrawlerContext) -> None:
        self.context = context
        self.closed = False

    async def new_context(
        self, *, base_url: str, storage_state: dict[str, object]
    ) -> FakeCrawlerContext:
        assert base_url == "https://erp.example.com"
        assert storage_state == {"cookies": [{"name": "sid", "value": "abc123"}]}
        return self.context

    async def close(self) -> None:
        self.closed = True


class FakeCrawlerChromium:
    def __init__(self, browser: FakeCrawlerBrowser) -> None:
        self.browser = browser
        self.headless_calls: list[bool] = []

    async def launch(self, *, headless: bool) -> FakeCrawlerBrowser:
        self.headless_calls.append(headless)
        return self.browser


class FakeCrawlerPlaywright:
    def __init__(self, chromium: FakeCrawlerChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class StateProbeAwareFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.current_route = "/dashboard"
        self.active_states: dict[str, str] = {}
        self.executed_probe_actions: list[str] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url
        if "//" in url:
            path = "/" + url.split("//", 1)[1].split("/", 1)[1] if "/" in url.split("//", 1)[1] else "/"
            self.current_route = path

    async def evaluate(self, script: str, *args):
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [
                {"path": "/dashboard", "title": "仪表盘"},
                {"path": "/users", "title": "用户管理"},
            ]
        if "__RUNLET_MENU_NODES__" in script:
            if self.current_route == "/users":
                return [
                    {"label": "用户管理", "route_path": "/users", "role": "menuitem"},
                    {"label": "禁用用户", "route_path": "/users", "role": "tab"},
                ]
            return [{"label": "仪表盘", "route_path": "/dashboard", "role": "menuitem"}]
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            if self.current_route == "/dashboard":
                return [
                    {
                        "page_route_path": "/dashboard",
                        "element_type": "button",
                        "role": "button",
                        "text": "刷新",
                    }
                ]
            state = self.active_states.get("/users", "default")
            if state == "tab=disabled":
                return [
                    {
                        "page_route_path": "/users",
                        "element_type": "table",
                        "role": "grid",
                        "text": "禁用用户列表",
                    }
                ]
            if state == "modal=create":
                return [
                    {
                        "page_route_path": "/users",
                        "element_type": "input",
                        "role": "textbox",
                        "text": "新增用户表单",
                    }
                ]
            if state == "page=2":
                return [
                    {
                        "page_route_path": "/users",
                        "element_type": "table",
                        "role": "grid",
                        "text": "第2页用户列表",
                    }
                ]
            return [
                {
                    "page_route_path": "/users",
                    "element_type": "table",
                    "role": "grid",
                    "text": "默认用户列表",
                },
                {
                    "page_route_path": "/users",
                    "element_type": "button",
                    "role": "button",
                    "text": "新增用户",
                },
                {
                    "page_route_path": "/users",
                    "element_type": "button",
                    "role": "button",
                    "text": "2",
                },
            ]
        if "__RUNLET_STATE_PROBE_EXECUTE__" in script:
            action = args[0] if args else {}
            if not isinstance(action, dict):
                action = {}
            entry_type = str(action.get("entry_type") or "")
            self.executed_probe_actions.append(entry_type)
            context = action.get("state_context")
            if not isinstance(context, dict):
                context = {}
            if entry_type == "tab_switch":
                self.active_states["/users"] = f"tab={context.get('active_tab', 'default')}"
            if entry_type == "open_modal":
                self.active_states["/users"] = f"modal={context.get('modal_title', 'create')}"
            if entry_type == "paginate_probe":
                self.active_states["/users"] = f"page={context.get('page_number', 1)}"
            return {"applied": True}
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


def install_fake_crawler_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    FakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = FakeCrawlerPage()
    context = FakeCrawlerContext(page)
    browser = FakeCrawlerBrowser(context)
    chromium = FakeCrawlerChromium(browser)
    playwright = FakeCrawlerPlaywright(chromium)

    class FakeAsyncPlaywrightStarter:
        async def start(self) -> FakeCrawlerPlaywright:
            return playwright

    module = ModuleType("playwright.async_api")
    module.async_playwright = lambda: FakeAsyncPlaywrightStarter()
    sys.modules["playwright.async_api"] = module
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    return page, context, browser, chromium, playwright


def install_state_probe_aware_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    StateProbeAwareFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = StateProbeAwareFakeCrawlerPage()
    context = FakeCrawlerContext(page)
    browser = FakeCrawlerBrowser(context)
    chromium = FakeCrawlerChromium(browser)
    playwright = FakeCrawlerPlaywright(chromium)

    class FakeAsyncPlaywrightStarter:
        async def start(self) -> FakeCrawlerPlaywright:
            return playwright

    module = ModuleType("playwright.async_api")
    module.async_playwright = lambda: FakeAsyncPlaywrightStarter()
    sys.modules["playwright.async_api"] = module
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    return page, context, browser, chromium, playwright


class RouteAwareFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.current_url = "about:blank"
        self.route_hints = [
            {"path": "/front/database/allInstance", "title": "总览"},
            {"path": "/front/database/dbInstance", "title": "数据库实例"},
        ]
        self.menu_nodes = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str):
        if "visibleSelector" in script:
            return True
        if "__RUNLET_ROUTE_HINTS__" in script:
            return self.route_hints
        if "__RUNLET_MENU_NODES__" in script:
            return self.menu_nodes
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            if self.current_url.endswith("/front/database/dbInstance"):
                return [
                    {
                        "page_route_path": "/front/database/dbInstance",
                        "element_type": "button",
                        "role": "button",
                        "text": "刷新",
                    }
                ]
            return []
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)

    async def close(self) -> None:
        self.closed = True


class FakeRouterExtractor:
    def __init__(self, result: CrawlExtractionResult) -> None:
        self.result = result
        self.calls = 0

    async def extract(self, *, browser_session, system, crawl_scope: str) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope
        self.calls += 1
        return self.result


class FakeDomMenuExtractor:
    def __init__(self, result: CrawlExtractionResult) -> None:
        self.result = result
        self.calls = 0

    async def extract(self, *, browser_session, system, crawl_scope: str) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope
        self.calls += 1
        return self.result


class FakePageDiscoveryExtractor:
    def __init__(self, result: CrawlExtractionResult) -> None:
        self.result = result
        self.calls = 0

    async def extract(self, *, browser_session, system, crawl_scope: str) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope
        self.calls += 1
        return self.result


class FakeStateProbeExtractor:
    def __init__(self, result: CrawlExtractionResult) -> None:
        self.result = result
        self.calls = 0

    async def extract(self, *, browser_session, system, crawl_scope: str) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope
        self.calls += 1
        return self.result


@pytest.mark.anyio
async def test_run_crawl_persists_snapshot_pages_and_elements(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    router_extractor = FakeRouterExtractor(
        CrawlExtractionResult(
            framework_detected="react",
            quality_score=0.92,
            pages=[
                PageCandidate(
                    route_path="/users",
                    page_title="用户管理",
                    page_summary="用户列表页面",
                    discovery_sources=["runtime_route_hints", "network_route_config"],
                    entry_candidates=[
                        {
                            "entry_type": "tab_switch",
                            "label": "用户列表",
                        }
                    ],
                    context_constraints={"auth_scope": "admin"},
                )
            ],
        )
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[
                MenuCandidate(
                    label="用户管理",
                    route_path="/users",
                    depth=0,
                    sort_order=0,
                    playwright_locator="role=menuitem[name='用户管理']",
                    page_route_path="/users",
                    discovery_sources=["dom_menu_tree"],
                    entry_candidates=[
                        {
                            "entry_type": "open_modal",
                            "label": "新增用户",
                        }
                    ],
                    context_constraints={"requires_permission": "user.read"},
                )
            ],
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="/users|tab=default",
                    state_context={"active_tab": "default"},
                    locator_candidates=[
                        {
                            "strategy_type": "semantic",
                            "selector": "role=button[name='新增用户']",
                        },
                        {
                            "strategy_type": "testid",
                            "selector": "data-testid=add-user",
                        },
                    ],
                    element_role="button",
                    element_text="新增用户",
                    playwright_locator="role=button[name='新增用户']",
                    stability_score=0.88,
                    usage_description="打开新增用户表单",
                )
            ],
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        router_extractor=router_extractor,
        dom_menu_extractor=dom_menu_extractor,
    )

    result = await crawler_service.run_crawl(
        system_id=seeded_auth_state.system_id,
        crawl_scope="full",
    )

    assert result.status == "success"
    assert result.snapshot_id is not None
    assert result.pages_saved == 1
    assert result.menus_saved == 1
    assert result.elements_saved == 1
    assert browser_factory.calls == [
        {
            "base_url": seeded_system.base_url,
            "storage_state": seeded_auth_state.storage_state,
        }
    ]
    assert browser_factory.session.closed is True
    assert router_extractor.calls == 1
    assert dom_menu_extractor.calls == 1

    snapshot = db_session.exec(select(CrawlSnapshot)).one()
    pages = db_session.exec(select(Page)).all()
    menus = db_session.exec(select(MenuNode)).all()
    elements = db_session.exec(select(PageElement)).all()

    assert snapshot.id == result.snapshot_id
    assert snapshot.framework_detected == "react"
    assert snapshot.quality_score == pytest.approx(0.92)
    assert snapshot.degraded is False
    assert len(pages) == 1
    assert pages[0].route_path == "/users"
    assert pages[0].discovery_sources == ["runtime_route_hints", "network_route_config"]
    assert pages[0].entry_candidates == [{"entry_type": "tab_switch", "label": "用户列表"}]
    assert pages[0].context_constraints == {"auth_scope": "admin"}
    assert len(menus) == 1
    assert menus[0].playwright_locator == "role=menuitem[name='用户管理']"
    assert menus[0].discovery_sources == ["dom_menu_tree"]
    assert menus[0].entry_candidates == [{"entry_type": "open_modal", "label": "新增用户"}]
    assert menus[0].context_constraints == {"requires_permission": "user.read"}
    assert len(elements) == 1
    assert elements[0].playwright_locator == "role=button[name='新增用户']"
    assert elements[0].state_signature == "/users|tab=default"
    assert elements[0].state_context == {"active_tab": "default"}
    assert elements[0].locator_candidates == [
        {
            "strategy_type": "semantic",
            "selector": "role=button[name='新增用户']",
        },
        {
            "strategy_type": "testid",
            "selector": "data-testid=add-user",
        },
    ]


@pytest.mark.anyio
async def test_run_crawl_uses_page_discovery_as_primary_page_source(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            quality_score=0.9,
            pages=[
                PageCandidate(route_path="/dashboard", page_title="仪表盘", discovery_sources=["runtime_route_hints"]),
                PageCandidate(
                    route_path="/users",
                    page_title="用户管理",
                    discovery_sources=["dom_menu_tree", "network_route_config"],
                ),
            ],
        )
    )
    router_extractor = FakeRouterExtractor(
        CrawlExtractionResult(pages=[PageCandidate(route_path="/legacy", page_title="遗留路由")])
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[
                MenuCandidate(
                    label="用户管理",
                    route_path="/users",
                    depth=0,
                    sort_order=0,
                    playwright_locator="role=menuitem[name='用户管理']",
                    page_route_path="/users",
                )
            ]
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        router_extractor=router_extractor,
        dom_menu_extractor=dom_menu_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.pages_saved == 2
    assert page_discovery_extractor.calls == 1
    assert router_extractor.calls == 0
    assert dom_menu_extractor.calls == 1

    pages = db_session.exec(select(Page).order_by(Page.route_path, Page.id)).all()
    assert [page.route_path for page in pages] == ["/dashboard", "/users"]


@pytest.mark.anyio
async def test_run_crawl_requires_valid_auth_state(
    db_session,
    seeded_system,
):
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=FakeBrowserFactory(),
        router_extractor=FakeRouterExtractor(CrawlExtractionResult()),
        dom_menu_extractor=FakeDomMenuExtractor(CrawlExtractionResult()),
    )

    result = await crawler_service.run_crawl(system_id=seeded_system.id, crawl_scope="full")

    assert result.status == "auth_required"
    assert result.snapshot_id is None
    assert db_session.exec(select(CrawlSnapshot)).all() == []


@pytest.mark.anyio
async def test_run_crawl_uses_default_real_extractors(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    browser_factory.session.route_hints = [
        {"path": "/dashboard", "title": "仪表盘"},
        {"path": "/users", "title": "用户管理"},
    ]
    browser_factory.session.dom_menu_nodes = [
        {"label": "仪表盘", "route_path": "/dashboard", "depth": 0, "order": 0, "role": "menuitem"},
        {"label": "用户管理", "route_path": "/users", "depth": 0, "order": 1, "role": "menuitem"},
    ]
    browser_factory.session.dom_elements = [
        {
            "page_route_path": "/users",
            "element_type": "button",
            "role": "button",
            "text": "新增用户",
            "usage_description": "打开新增用户弹窗",
        }
    ]
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.pages_saved == 2
    assert result.menus_saved == 2
    assert result.elements_saved == 1
    assert result.snapshot_id is not None
    assert result.failure_reason is None
    assert result.warning_messages == []
    assert result.degraded is False
    assert "storage_state" not in result.model_dump()

    snapshot = db_session.exec(select(CrawlSnapshot)).one()
    pages = db_session.exec(select(Page)).all()
    menus = db_session.exec(select(MenuNode)).all()
    elements = db_session.exec(select(PageElement)).all()

    assert snapshot.degraded is False
    assert snapshot.failure_reason is None
    assert snapshot.warning_messages == []
    assert len(pages) == 2
    assert len(menus) == 2
    assert all((menu.playwright_locator or "").startswith("role=menuitem") for menu in menus)
    assert len(elements) == 1
    assert elements[0].playwright_locator == "role=button[name='新增用户']"


@pytest.mark.anyio
async def test_run_crawl_persists_failure_warning_and_degraded_metadata(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    browser_factory.session.raise_route_hint_error = True
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.pages_saved == 0
    assert result.failure_reason is not None
    assert "route hints unavailable" in result.failure_reason
    assert result.warning_messages
    assert result.degraded is True

    snapshot = db_session.exec(select(CrawlSnapshot)).one()
    assert snapshot.degraded is True
    assert snapshot.failure_reason is not None
    assert "route hints unavailable" in snapshot.failure_reason
    assert snapshot.warning_messages


@pytest.mark.anyio
async def test_run_crawl_enriches_menu_routes_from_runtime_titles(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    browser_factory.session.route_hints = [
        {"path": "/front/database/allInstance", "title": "总览_智慧运维管理平台"},
        {"path": "/front/alerter", "title": "告警中心"},
    ]
    browser_factory.session.dom_menu_nodes = [
        {"label": "总览", "depth": 0, "order": 0, "role": "menuitem"},
        {"label": "告警中心", "depth": 0, "order": 1, "role": "menuitem"},
    ]
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    menus = db_session.exec(select(MenuNode).order_by(MenuNode.sort_order, MenuNode.id)).all()
    pages = db_session.exec(select(Page).order_by(Page.route_path, Page.id)).all()
    page_by_route = {page.route_path: page for page in pages}

    assert len(menus) == 2
    assert menus[0].route_path == "/front/database/allInstance"
    assert menus[0].page_id == page_by_route["/front/database/allInstance"].id
    assert menus[1].route_path == "/front/alerter"
    assert menus[1].page_id == page_by_route["/front/alerter"].id


@pytest.mark.anyio
async def test_dom_menu_traversal_extractor_skips_hidden_tables_and_normalizes_visible_grids():
    extractor = DomMenuTraversalExtractor()
    browser_session = FakeBrowserSession()
    browser_session.dom_elements = [
        {
            "page_route_path": "/front/database/allInstance",
            "element_type": "table",
            "text": "隐藏总览表格",
            "visible": False,
        },
        {
            "page_route_path": "/front/database/dbInstance",
            "element_type": "div",
            "role": "grid",
            "class_name": "el-table el-table--small",
            "text": "实例列表",
            "visible": True,
        },
    ]

    result = await extractor.extract(
        browser_session=browser_session,
        system=None,
        crawl_scope="full",
    )

    assert [(element.page_route_path, element.element_type, element.element_role) for element in result.elements] == [
        ("/front/database/dbInstance", "table", "grid")
    ]


@pytest.mark.anyio
async def test_playwright_browser_factory_collects_dom_elements_across_discovered_routes(
    monkeypatch: pytest.MonkeyPatch,
):
    page = RouteAwareFakeCrawlerPage()
    context = FakeCrawlerContext(page)
    browser = FakeCrawlerBrowser(context)
    chromium = FakeCrawlerChromium(browser)
    playwright = FakeCrawlerPlaywright(chromium)

    class FakeAsyncPlaywrightStarter:
        async def start(self) -> FakeCrawlerPlaywright:
            return playwright

    module = ModuleType("playwright.async_api")
    module.async_playwright = lambda: FakeAsyncPlaywrightStarter()
    sys.modules["playwright.async_api"] = module
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)

    factory = PlaywrightBrowserFactory()
    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert dom_elements == [
        {
            "page_route_path": "/front/database/dbInstance",
            "element_type": "button",
            "role": "button",
            "text": "刷新",
        }
    ]
    assert page.goto_calls == [
        ("https://erp.example.com", "domcontentloaded"),
        ("https://erp.example.com/front/database/allInstance", "domcontentloaded"),
        ("https://erp.example.com/front/database/dbInstance", "domcontentloaded"),
    ]
    assert page.wait_for_timeout_calls[0] == 5000
    assert page.wait_for_timeout_calls.count(2000) >= 2
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_collects_dom_elements_from_menu_routes_when_runtime_hints_are_partial(
    monkeypatch: pytest.MonkeyPatch,
):
    page = RouteAwareFakeCrawlerPage()
    page.route_hints = [{"path": "/front/database/allInstance", "title": "总览"}]
    page.menu_nodes = [
        {"label": "数据库实例", "route_path": "/front/database/dbInstance", "role": "menuitem"}
    ]
    context = FakeCrawlerContext(page)
    browser = FakeCrawlerBrowser(context)
    chromium = FakeCrawlerChromium(browser)
    playwright = FakeCrawlerPlaywright(chromium)

    class FakeAsyncPlaywrightStarter:
        async def start(self) -> FakeCrawlerPlaywright:
            return playwright

    module = ModuleType("playwright.async_api")
    module.async_playwright = lambda: FakeAsyncPlaywrightStarter()
    sys.modules["playwright.async_api"] = module
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)

    factory = PlaywrightBrowserFactory()
    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert dom_elements == [
        {
            "page_route_path": "/front/database/dbInstance",
            "element_type": "button",
            "role": "button",
            "text": "刷新",
        }
    ]
    assert page.goto_calls == [
        ("https://erp.example.com", "domcontentloaded"),
        ("https://erp.example.com/front/database/allInstance", "domcontentloaded"),
        ("https://erp.example.com/front/database/dbInstance", "domcontentloaded"),
    ]


@pytest.mark.anyio
async def test_playwright_browser_factory_session_collects_runtime_facts(monkeypatch):
    page, context, browser, chromium, playwright = install_fake_crawler_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    network_route_configs = await session.collect_network_route_configs(crawl_scope="full")
    network_resource_hints = await session.collect_network_resource_hints(crawl_scope="full")
    network_requests = await session.collect_network_requests(crawl_scope="full")
    page_metadata = await session.collect_page_metadata(crawl_scope="full")
    await session.close()

    assert route_hints[0]["path"] == "/dashboard"
    assert menu_nodes[1]["label"] == "用户管理"
    assert dom_elements[0]["element_type"] == "button"
    assert network_route_configs[0]["route_path"] == "/reports"
    assert network_resource_hints[0]["route_path"] == "/users"
    assert network_requests[0]["path"] == "/dashboard"
    assert len(page_metadata) == 1
    assert page_metadata[0]["route_path"] == "/users"
    assert page_metadata[0]["status_code"] == 200
    assert page.goto_calls == [
        ("https://erp.example.com", "domcontentloaded"),
        ("https://erp.example.com/dashboard", "domcontentloaded"),
        ("https://erp.example.com/users", "domcontentloaded"),
    ]
    assert page.wait_for_timeout_calls[0] == 5000
    assert page.wait_for_timeout_calls.count(2000) >= 2
    assert page.route_snapshot_eval_calls >= 2
    assert page.readiness_shell_eval_calls >= 2
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_session_collects_resolved_route_snapshot(monkeypatch):
    page, context, browser, chromium, playwright = install_fake_crawler_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    await session.collect_dom_elements(crawl_scope="full")
    snapshot = await session.collect_route_snapshot(crawl_scope="current")
    await session.close()

    assert snapshot["resolved_route"] == "/users"
    assert snapshot["route_source"] in {"pathname", "router", "hash", "history"}
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_readiness_polling_is_used_once_and_cached(monkeypatch):
    page, context, browser, chromium, playwright = install_fake_crawler_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    await session.collect_route_hints(crawl_scope="full")
    first_snapshot_samples = page.route_snapshot_eval_calls
    first_shell_samples = page.readiness_shell_eval_calls

    await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert first_snapshot_samples >= 2
    assert first_shell_samples >= 2
    assert page.route_snapshot_eval_calls == first_snapshot_samples
    assert page.readiness_shell_eval_calls == first_shell_samples
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_readiness_degrades_when_content_probe_fails(monkeypatch):
    page, context, browser, chromium, playwright = install_fake_crawler_async_api(monkeypatch)
    page.fail_content_probe = True
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert route_hints
    assert route_hints[0]["path"] == "/dashboard"
    assert page.route_snapshot_eval_calls >= 2
    assert page.readiness_shell_eval_calls >= 2
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_session_exposes_controlled_state_probe_hooks(monkeypatch):
    page, context, browser, chromium, playwright = install_fake_crawler_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    baseline = await session.collect_state_probe_baseline(crawl_scope="full")
    actions = await session.collect_state_probe_actions(crawl_scope="full")
    executed = await session.perform_state_probe_action(
        action={
            "route_path": "/users",
            "entry_type": "tab_switch",
            "state_context": {"active_tab": "default"},
        },
        crawl_scope="full",
    )
    await session.close()

    assert baseline
    assert isinstance(baseline[0], dict)
    assert baseline[0]["route_path"] in {"/dashboard", "/users"}
    assert baseline[0]["state_context"] == {"active_tab": "default"}
    assert isinstance(baseline[0]["elements"], list)
    assert actions
    assert all("entry_type" in action for action in actions)
    assert executed["route_path"] == "/users"
    assert executed["state_context"] == {"active_tab": "default"}
    assert isinstance(executed["elements"], list)
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_state_probe_executes_real_action_specific_states(monkeypatch):
    page, context, browser, chromium, playwright = install_state_probe_aware_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    tab_result = await session.perform_state_probe_action(
        action={
            "route_path": "/users",
            "entry_type": "tab_switch",
            "state_context": {"active_tab": "disabled"},
        },
        crawl_scope="full",
    )
    modal_result = await session.perform_state_probe_action(
        action={
            "route_path": "/users",
            "entry_type": "open_modal",
            "state_context": {"modal_title": "create"},
        },
        crawl_scope="full",
    )
    pagination_result = await session.perform_state_probe_action(
        action={
            "route_path": "/users",
            "entry_type": "paginate_probe",
            "state_context": {"page_number": 2},
        },
        crawl_scope="full",
    )
    await session.close()

    assert any(item.get("text") == "禁用用户列表" for item in tab_result["elements"])
    assert any(item.get("text") == "新增用户表单" for item in modal_result["elements"])
    assert any(item.get("text") == "第2页用户列表" for item in pagination_result["elements"])
    assert page.executed_probe_actions == ["tab_switch", "open_modal", "paginate_probe"]
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_state_probe_actions_include_non_current_discovered_routes(monkeypatch):
    page, context, browser, chromium, playwright = install_state_probe_aware_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    actions = await session.collect_state_probe_actions(crawl_scope="full")
    await session.close()

    assert any(action.get("route_path") == "/users" for action in actions)
    assert any(action.get("entry_type") in {"tab_switch", "open_modal", "paginate_probe"} for action in actions)
    assert any(call[0].endswith("/users") for call in page.goto_calls)
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_metadata_reports_current_page_only(monkeypatch):
    page, context, browser, chromium, playwright = install_fake_crawler_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    # Drive route transitions first, then collect metadata for current loaded page only.
    await session.collect_dom_elements(crawl_scope="full")
    page_metadata = await session.collect_page_metadata(crawl_scope="full")
    await session.close()

    assert page_metadata == [
        {"route_path": "/users", "page_title": "用户管理", "reachable": True, "status_code": 200}
    ]


@pytest.mark.anyio
async def test_run_crawl_merges_state_probe_elements_with_state_context(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            quality_score=0.91,
            pages=[
                PageCandidate(route_path="/users", page_title="用户管理", discovery_sources=["runtime_route_hints"]),
            ],
        )
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[
                MenuCandidate(
                    label="用户管理",
                    route_path="/users",
                    page_route_path="/users",
                    playwright_locator="role=menuitem[name='用户管理']",
                )
            ]
        )
    )
    state_probe_extractor = FakeStateProbeExtractor(
        CrawlExtractionResult(
            quality_score=0.77,
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:default",
                    state_context={"active_tab": "default"},
                    locator_candidates=[
                        {
                            "strategy_type": "semantic",
                            "selector": "role=button[name='新增用户']",
                        }
                    ],
                    playwright_locator="role=button[name='新增用户']",
                    element_role="button",
                    element_text="新增用户",
                ),
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:modal=create",
                    state_context={"modal_title": "create"},
                    locator_candidates=[
                        {
                            "strategy_type": "semantic",
                            "selector": "role=button[name='确认']",
                        }
                    ],
                    playwright_locator="role=button[name='确认']",
                    element_role="button",
                    element_text="确认",
                ),
            ],
            warning_messages=["interaction_budget_exhausted"],
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=state_probe_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.pages_saved == 1
    assert result.menus_saved == 1
    assert result.elements_saved == 2
    assert result.warning_messages == ["interaction_budget_exhausted"]
    assert state_probe_extractor.calls == 1

    elements = db_session.exec(select(PageElement).order_by(PageElement.state_signature, PageElement.id)).all()
    assert [element.state_signature for element in elements] == ["users:default", "users:modal=create"]
    assert elements[0].state_context == {"active_tab": "default"}
    assert elements[0].locator_candidates == [
        {
            "strategy_type": "semantic",
            "selector": "role=button[name='新增用户']",
        }
    ]


@pytest.mark.anyio
async def test_run_crawl_merges_probe_and_dom_stateful_elements_instead_of_replacing(
    db_session,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            pages=[PageCandidate(route_path="/users", page_title="用户管理")],
        )
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[MenuCandidate(label="用户管理", route_path="/users", page_route_path="/users")],
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:default",
                    state_context={"active_tab": "default"},
                    playwright_locator="role=button[name='刷新']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=button[name='刷新']"},
                    ],
                    element_role="button",
                    element_text="刷新",
                )
            ],
        )
    )
    state_probe_extractor = FakeStateProbeExtractor(
        CrawlExtractionResult(
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:modal=create",
                    state_context={"modal_title": "create"},
                    playwright_locator="role=button[name='确认']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=button[name='确认']"},
                    ],
                    element_role="button",
                    element_text="确认",
                )
            ]
        )
    )

    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=state_probe_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.elements_saved == 2
    elements = db_session.exec(select(PageElement).order_by(PageElement.state_signature, PageElement.id)).all()
    assert [element.state_signature for element in elements] == ["users:default", "users:modal=create"]


@pytest.mark.anyio
async def test_run_crawl_preserves_multiple_elements_under_same_state_signature(
    db_session,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(pages=[PageCandidate(route_path="/users", page_title="用户管理")]),
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(menus=[MenuCandidate(label="用户管理", route_path="/users", page_route_path="/users")])
    )
    state_probe_extractor = FakeStateProbeExtractor(
        CrawlExtractionResult(
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:tab=disabled",
                    state_context={"active_tab": "disabled"},
                    element_role="button",
                    element_text="启用用户",
                    playwright_locator="role=button[name='启用用户']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=button[name='启用用户']"},
                    ],
                ),
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:tab=disabled",
                    state_context={"active_tab": "disabled"},
                    element_role="button",
                    element_text="批量恢复",
                    playwright_locator="role=button[name='批量恢复']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=button[name='批量恢复']"},
                    ],
                ),
            ]
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=state_probe_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.elements_saved == 2
    elements = db_session.exec(select(PageElement).order_by(PageElement.element_text, PageElement.id)).all()
    assert [element.state_signature for element in elements] == ["users:tab=disabled", "users:tab=disabled"]
    assert [element.element_text for element in elements] == ["启用用户", "批量恢复"]


@pytest.mark.anyio
async def test_run_crawl_merges_same_element_from_dom_and_probe_with_enriched_metadata(
    db_session,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(pages=[PageCandidate(route_path="/users", page_title="用户管理")]),
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[MenuCandidate(label="用户管理", route_path="/users", page_route_path="/users")],
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:default",
                    state_context={"active_tab": "default"},
                    element_role="button",
                    element_text="新增用户",
                    playwright_locator="role=button[name='新增用户']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=button[name='新增用户']"},
                    ],
                    attributes={"data_testid": "create-user"},
                )
            ],
        )
    )
    state_probe_extractor = FakeStateProbeExtractor(
        CrawlExtractionResult(
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
                    state_signature="users:default",
                    state_context={"modal_title": "create"},
                    element_role="button",
                    element_text="新增用户",
                    playwright_locator="text='新增用户'",
                    locator_candidates=[
                        {"strategy_type": "text", "selector": "text='新增用户'"},
                    ],
                    attributes={"aria_label": "新增用户"},
                )
            ]
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=state_probe_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.elements_saved == 1
    elements = db_session.exec(select(PageElement)).all()
    assert len(elements) == 1
    assert elements[0].element_text == "新增用户"
    assert elements[0].state_signature == "users:default"
    assert elements[0].locator_candidates == [
        {"strategy_type": "semantic", "selector": "role=button[name='新增用户']"},
        {"strategy_type": "text", "selector": "text='新增用户'"},
    ]
    assert elements[0].attributes == {"data_testid": "create-user", "aria_label": "新增用户"}
    assert elements[0].state_context == {"active_tab": "default", "modal_title": "create"}


@pytest.mark.anyio
async def test_task6_crawl_baseline_state_signature_elements_keep_locator_candidates(
    db_session,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            pages=[PageCandidate(route_path="/users", page_title="用户管理")],
        )
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[MenuCandidate(label="用户管理", route_path="/users", page_route_path="/users")],
        )
    )
    state_probe_extractor = FakeStateProbeExtractor(
        CrawlExtractionResult(
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="table",
                    state_signature="users:default",
                    state_context={"entry_type": "default"},
                    element_role="table",
                    element_text="用户列表",
                    playwright_locator="role=table[name='用户列表']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=table[name='用户列表']"},
                    ],
                ),
                ElementCandidate(
                    page_route_path="/users",
                    element_type="dialog",
                    state_signature="users:modal=create",
                    state_context={"entry_type": "open_modal"},
                    element_role="dialog",
                    element_text="新增用户",
                    playwright_locator="role=dialog[name='新增用户']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=dialog[name='新增用户']"},
                    ],
                ),
            ]
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=state_probe_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.elements_saved == 2

    elements = db_session.exec(select(PageElement).order_by(PageElement.state_signature, PageElement.id)).all()
    assert [element.state_signature for element in elements] == ["users:default", "users:modal=create"]
    assert all(element.locator_candidates for element in elements)
    assert elements[0].locator_candidates[0]["strategy_type"] == "semantic"
