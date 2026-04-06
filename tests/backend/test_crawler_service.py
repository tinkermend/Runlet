import sys
from datetime import UTC, datetime
from types import ModuleType
from urllib.parse import urlparse

import pytest
from sqlmodel import select

from app.domains.auth_service.schemas import AuthRefreshResult
from app.domains.crawler_service.schemas import (
    CrawlExtractionResult,
    ElementCandidate,
    MenuCandidate,
    PageCandidate,
)
from app.domains.crawler_service.extractors.dom_menu import (
    DomMenuTraversalExtractor,
    merge_menu_skeleton_and_materialized_nodes,
)
from app.domains.crawler_service.extractors.state_probe import ControlledStateProbeExtractor
from app.domains.crawler_service.service import (
    CrawlerService,
    PlaywrightBrowserFactory,
    _derive_crawl_entry_url,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.systems import AuthState
from app.shared.enums import AuthStateStatus


def test_page_element_schema_exposes_state_and_locator_candidates():
    assert "state_signature" in ElementCandidate.model_fields
    assert "state_context" in ElementCandidate.model_fields
    assert "locator_candidates" in ElementCandidate.model_fields


def test_crawl_candidates_expose_navigation_metadata_fields():
    assert "navigation_diagnostics" in PageCandidate.model_fields
    assert "materialized_by" in ElementCandidate.model_fields
    assert "navigation_diagnostics" in ElementCandidate.model_fields
    assert "navigation_identity" in MenuCandidate.model_fields
    assert "parent_navigation_identity" in MenuCandidate.model_fields


def test_derive_crawl_entry_url_prefers_login_redirect_hash_route():
    assert (
        _derive_crawl_entry_url(
            base_url="https://hotgo.facms.cn",
            login_url="https://hotgo.facms.cn/admin#/login?redirect=/dashboard",
        )
        == "https://hotgo.facms.cn/admin#/dashboard"
    )


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
        entry_url: str | None = None,
    ) -> FakeBrowserSession:
        self.calls.append(
            {
                "base_url": base_url,
                "storage_state": storage_state,
                "entry_url": entry_url,
            }
        )
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


class PerVisitReadinessFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.current_url = "about:blank"
        self.route_snapshot_eval_calls = 0
        self.readiness_shell_urls: list[str] = []
        self.route_ready_urls: list[str] = []
        self._settled_paths: set[str] = set()

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str):
        parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
        current_path = parsed.path or "/"
        if "document.readyState" in script and "shell_ready" in script:
            self.readiness_shell_urls.append(current_path)
            return {"shell_ready": current_path in self._settled_paths}
        if "visibleSelector" in script:
            self.route_ready_urls.append(current_path)
            return current_path in self._settled_paths
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            self.route_snapshot_eval_calls += 1
            return {
                "pathname": current_path,
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [
                {"path": "/dashboard", "title": "仪表盘"},
                {"path": "/users", "title": "用户管理"},
            ]
        if "__RUNLET_MENU_NODES__" in script:
            return []
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            return [
                {
                    "page_route_path": current_path,
                    "element_type": "button",
                    "role": "button",
                    "text": f"按钮{current_path}",
                }
            ]
        if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
            return []
        if "__RUNLET_NETWORK_RESOURCES__" in script:
            return []
        if "__RUNLET_NETWORK_REQUESTS__" in script:
            return []
        if "__RUNLET_PAGE_METADATA__" in script:
            return []
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
        current_path = parsed.path or "/"
        if timeout >= 2000:
            self._settled_paths.add(current_path)

    async def close(self) -> None:
        self.closed = True


class HashRouteCurrentScopeFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.current_url = "about:blank"
        self._settled = False

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = "https://erp.example.com/#/users" if url == "https://erp.example.com" else url

    async def evaluate(self, script: str):
        parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/#/users")
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self._settled}
        if "visibleSelector" in script:
            return self._settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            return {
                "pathname": parsed.path or "/",
                "location_hash": "#/users",
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/users", "title": "用户管理"}]
        if "__RUNLET_MENU_NODES__" in script:
            return []
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            return [
                {
                    "page_route_path": "/",
                    "element_type": "button",
                    "role": "button",
                    "text": "新增用户",
                }
            ]
        if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
            return []
        if "__RUNLET_NETWORK_RESOURCES__" in script:
            return []
        if "__RUNLET_NETWORK_REQUESTS__" in script:
            return []
        if "__RUNLET_PAGE_METADATA__" in script:
            return []
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 2000:
            self._settled = True

    async def close(self) -> None:
        self.closed = True


class HashRouteFullScopeFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.current_url = "about:blank"
        self._settled = False

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str):
        parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/admin#/dashboard")
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self._settled}
        if "visibleSelector" in script:
            return self._settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            return {
                "pathname": parsed.path or "/admin",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [
                {"path": "/dashboard/console", "title": "主控台"},
                {"path": "/permission/role", "title": "角色权限"},
            ]
        if "__RUNLET_MENU_NODES__" in script:
            return []
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            if parsed.fragment == "/dashboard/console":
                return [
                    {
                        "page_route_path": "/",
                        "element_type": "button",
                        "role": "button",
                        "text": "刷新主控台",
                    }
                ]
            if parsed.fragment == "/permission/role":
                return [
                    {
                        "page_route_path": "/",
                        "element_type": "table",
                        "role": "grid",
                        "text": "角色权限表格",
                    }
                ]
            return []
        if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
            return []
        if "__RUNLET_NETWORK_RESOURCES__" in script:
            return []
        if "__RUNLET_NETWORK_REQUESTS__" in script:
            return []
        if "__RUNLET_PAGE_METADATA__" in script:
            return []
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 2000:
            self._settled = True

    async def close(self) -> None:
        self.closed = True


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
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": self.current_route,
                "history_route": None,
            }
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
        if "__RUNLET_PAGE_METADATA__" in script:
            return [
                {
                    "route_path": self.current_route,
                    "page_title": "用户管理" if self.current_route == "/users" else "仪表盘",
                    "reachable": True,
                    "status_code": 200,
                }
            ]
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


def install_per_visit_readiness_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    PerVisitReadinessFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = PerVisitReadinessFakeCrawlerPage()
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


def install_hash_route_current_scope_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    HashRouteCurrentScopeFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = HashRouteCurrentScopeFakeCrawlerPage()
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


def install_hash_route_full_scope_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    HashRouteFullScopeFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = HashRouteFullScopeFakeCrawlerPage()
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


class HotgoLikeFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.current_url = "about:blank"
        self.current_route = "/"
        self.current_hash = "#/dashboard"
        self.settle_phase = 0
        self.materialize_calls: list[list[dict[str, object]]] = []
        self.route_snapshot_eval_calls = 0
        self.readiness_shell_eval_calls = 0
        self.executed_probe_actions: list[str] = []
        self.active_states: dict[str, str] = {}
        self.route_hints = [
            {"path": "/dashboard", "title": "工作台"},
            {"path": "/workbench", "title": "分析页"},
        ]
        self.skeleton_menu_routes = ["/dashboard", "/workbench"]

    async def goto(self, url: str, *, wait_until: str) -> None:
        del wait_until
        self.goto_calls.append((url, "domcontentloaded"))
        self.current_url = url
        parsed = urlparse(url if url.startswith("http") else "https://erp.example.com/")
        if parsed.path and parsed.path != "/":
            self.current_route = parsed.path
            self.current_hash = None

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            self.readiness_shell_eval_calls += 1
            return {"shell_ready": self.settle_phase >= 2}
        if "visibleSelector" in script:
            return self.settle_phase >= 3
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            self.route_snapshot_eval_calls += 1
            if self.current_route == "/":
                return {
                    "pathname": "/",
                    "location_hash": self.current_hash,
                    "router_route": None,
                    "history_route": None,
                }
            return {
                "pathname": self.current_route,
                "location_hash": None,
                "router_route": self.current_route,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return self.route_hints
        if "__RUNLET_MENU_NODES__" in script:
            nodes = [
                {
                    "label": "工作台",
                    "route_path": self.skeleton_menu_routes[0],
                    "page_route_path": self.skeleton_menu_routes[0],
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                },
                {
                    "label": "分析页",
                    "route_path": self.skeleton_menu_routes[1],
                    "page_route_path": self.skeleton_menu_routes[1],
                    "depth": 0,
                    "order": 1,
                    "role": "menuitem",
                },
                {
                    "label": "系统管理",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 0,
                    "order": 2,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                    "aria_expanded": "true" if self.settle_phase >= 3 else "false",
                },
            ]
            return nodes
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            if self.settle_phase >= 3 and any(target.get("label") == "系统管理" for target in normalized_targets):
                return [
                    {
                        "label": "用户管理",
                        "route_path": "/system/users",
                        "page_route_path": "/system/users",
                        "depth": 1,
                        "order": 3,
                        "role": "menuitem",
                        "parent_label": "系统管理",
                    }
                ]
            return []
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
            if self.current_route == "/workbench":
                return [
                    {
                        "page_route_path": "/workbench",
                        "element_type": "table",
                        "role": "grid",
                        "text": "访问统计",
                    }
                ]
            if self.current_route == "/system/users":
                state = self.active_states.get("/system/users", "default")
                if state == "tab=disabled":
                    return [
                        {
                            "page_route_path": "/system/users",
                            "element_type": "table",
                            "role": "grid",
                            "text": "禁用用户列表",
                        }
                    ]
                if state == "page=2":
                    return [
                        {
                            "page_route_path": "/system/users",
                            "element_type": "table",
                            "role": "grid",
                            "text": "第2页用户列表",
                        }
                    ]
                return [
                    {
                        "page_route_path": "/system/users",
                        "element_type": "table",
                        "role": "grid",
                        "text": "用户列表",
                    },
                    {
                        "page_route_path": "/system/users",
                        "element_type": "button",
                        "role": "button",
                        "text": "新增用户",
                    },
                    {
                        "page_route_path": "/system/users",
                        "element_type": "tab",
                        "role": "tab",
                        "text": "禁用",
                    },
                    {
                        "page_route_path": "/system/users",
                        "element_type": "button",
                        "role": "button",
                        "text": "2",
                    },
                ]
            return []
        if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
            return []
        if "__RUNLET_NETWORK_RESOURCES__" in script:
            return []
        if "__RUNLET_NETWORK_REQUESTS__" in script:
            return []
        if "__RUNLET_STATE_PROBE_EXECUTE__" in script:
            action = args[0] if args else {}
            if not isinstance(action, dict):
                action = {}
            entry_type = str(action.get("entry_type") or "")
            self.executed_probe_actions.append(entry_type)
            context = action.get("state_context")
            if not isinstance(context, dict):
                context = {}
            if self.current_route == "/system/users" and entry_type == "tab_switch":
                self.active_states["/system/users"] = f"tab={context.get('active_tab', 'default')}"
                return {"applied": True}
            if self.current_route == "/system/users" and entry_type == "paginate_probe":
                self.active_states["/system/users"] = f"page={context.get('page_number', 1)}"
                return {"applied": True}
            return {"applied": False, "reason": "action_not_applied"}
        if "__RUNLET_PAGE_METADATA__" in script:
            titles = {
                "/dashboard": "工作台",
                "/workbench": "分析页",
                "/system/users": "用户管理",
            }
            return [
                {
                    "route_path": self.current_route,
                    "page_title": titles.get(self.current_route, "HotGo"),
                    "reachable": True,
                    "status_code": 200,
                }
            ]
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settle_phase = max(self.settle_phase, 1)
            return
        if timeout >= 2000:
            self.settle_phase += 1
            if self.current_route == "/" and self.settle_phase >= 4:
                self.current_route = "/dashboard"
                self.current_hash = None

    async def close(self) -> None:
        self.closed = True


class HotgoLikeFakeCrawlerBrowser(FakeCrawlerBrowser):
    async def new_context(
        self, *, base_url: str, storage_state: dict[str, object]
    ) -> FakeCrawlerContext:
        assert base_url == "https://erp.example.com"
        assert storage_state.get("cookies") == [{"name": "sid", "value": "abc123"}]
        return self.context


def install_hotgo_like_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    HotgoLikeFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = HotgoLikeFakeCrawlerPage()
    context = FakeCrawlerContext(page)
    browser = HotgoLikeFakeCrawlerBrowser(context)
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


class MaterializeAwareFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.materialize_calls: list[list[dict[str, object]]] = []
        self.menu_expanded = False
        self.route_hints = [{"path": "/dashboard", "title": "仪表盘"}]

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return self.route_hints
        if "__RUNLET_MENU_NODES__" in script:
            nodes = [
                {
                    "label": "权限管理",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                    "aria_expanded": "false" if not self.menu_expanded else "true",
                }
            ]
            if self.menu_expanded:
                nodes.append(
                    {
                        "label": "管理员列表",
                        "route_path": "/system/admin",
                        "page_route_path": "/system/admin",
                        "depth": 1,
                        "order": 1,
                        "role": "menuitem",
                        "parent_label": "权限管理",
                    }
                )
            return nodes
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            if any(target.get("label") == "权限管理" for target in normalized_targets):
                self.menu_expanded = True
            return [
                {
                    "label": "管理员列表",
                    "route_path": "/system/admin",
                    "page_route_path": "/system/admin",
                    "depth": 1,
                    "order": 1,
                    "role": "menuitem",
                    "parent_label": "权限管理",
                }
            ]
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            if self.current_url.endswith("/system/admin"):
                return [
                    {
                        "page_route_path": "/system/admin",
                        "element_type": "button",
                        "role": "button",
                        "text": "新增管理员",
                    }
                ]
            return []
        if "__RUNLET_NETWORK_ROUTE_CONFIGS__" in script:
            return []
        if "__RUNLET_NETWORK_RESOURCES__" in script:
            return []
        if "__RUNLET_NETWORK_REQUESTS__" in script:
            return []
        if "__RUNLET_PAGE_METADATA__" in script:
            return []
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


class NaiveCollapsedMenuFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.materialize_calls: list[list[dict[str, object]]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/admin#/dashboard")
            return {
                "pathname": parsed.path or "/admin",
                "location_hash": "#/dashboard",
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/admin", "title": "主控台"}]
        if "__RUNLET_MENU_NODES__" in script:
            if (
                "n-menu-item-content--collapsed" not in script
                or 'querySelector(".n-menu-item-content--collapsed")' not in script
            ):
                return [
                    {
                        "label": "权限管理",
                        "route_path": None,
                        "page_route_path": None,
                        "depth": 0,
                        "order": 0,
                        "role": "menuitem",
                        "entry_type": None,
                    }
                ]
            return [
                {
                    "label": "权限管理",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                }
            ]
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            if ".n-menu-item-content" not in script or "parentElement?.closest" not in script:
                return []
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            return [
                {
                    "label": "角色权限",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 1,
                    "order": 1,
                    "role": "menuitem",
                    "parent_label": "权限管理",
                }
            ]
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
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


class ClickDiscoverRouteFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.current_title = "主控台"
        self.materialize_calls: list[list[dict[str, object]]] = []
        self.click_targets: list[dict[str, object]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url
        if "#/permission/role" not in url:
            self.current_title = "主控台"

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/admin#/dashboard")
            return {
                "pathname": parsed.path or "/admin",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else "#/dashboard/console",
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/admin", "title": "主控台"}]
        if "__RUNLET_MENU_NODES__" in script:
            return [
                {
                    "label": "权限管理",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                }
            ]
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            if ".n-menu-item-content" not in script or "parentElement?.closest" not in script:
                return []
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            return [
                {
                    "label": "角色权限",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 1,
                    "order": 1,
                    "role": "menuitem",
                    "parent_label": "权限管理",
                }
            ]
        if "__RUNLET_CLICK_NAVIGATION_TARGET__" in script:
            if ".n-menu-item-content" not in script:
                return {"clicked": False}
            target = dict(args[0]) if args and isinstance(args[0], dict) else {}
            self.click_targets.append(target)
            if target.get("label") == "角色权限":
                self.current_url = "https://erp.example.com/admin#/permission/role"
                self.current_title = "角色权限"
                return {"clicked": True}
            return {"clicked": False}
        if "document.title" in script:
            return self.current_title
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
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


class MissingLocator:
    def nth(self, _index: int):
        return self

    def locator(self, _selector: str):
        return self

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 0

    async def click(self, **_kwargs) -> None:
        raise AssertionError("click should not be attempted for missing locator")

    async def dispatch_event(self, _event_name: str) -> None:
        raise AssertionError("dispatch_event should not be attempted for missing locator")


class LocatorFallbackMissingLeafFakeCrawlerPage(ClickDiscoverRouteFakeCrawlerPage):
    async def evaluate(self, script: str, *args):
        if "__RUNLET_CLICK_NAVIGATION_TARGET__" in script:
            return {"clicked": False}
        return await super().evaluate(script, *args)

    def get_by_role(self, _role: str, **_kwargs):
        return MissingLocator()


class SuccessfulLeafLocator:
    def __init__(self, page: "StaleJsClickThenLocatorNavigateFakeCrawlerPage") -> None:
        self.page = page

    def nth(self, _index: int):
        return self

    def locator(self, _selector: str):
        return self

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 1

    async def click(self, **_kwargs) -> None:
        self.page.current_url = "https://erp.example.com/admin#/permission/role"
        self.page.current_title = "角色权限"

    async def dispatch_event(self, _event_name: str) -> None:
        await self.click()


class StaleJsClickThenLocatorNavigateFakeCrawlerPage(ClickDiscoverRouteFakeCrawlerPage):
    async def evaluate(self, script: str, *args):
        if "__RUNLET_CLICK_NAVIGATION_TARGET__" in script:
            target = dict(args[0]) if args and isinstance(args[0], dict) else {}
            self.click_targets.append(target)
            return {"clicked": True}
        return await super().evaluate(script, *args)

    def get_by_role(self, _role: str, **_kwargs):
        return SuccessfulLeafLocator(self)


class ParentExpansionLocator:
    def __init__(
        self,
        page: "ParentLocatorExpansionRequiredFakeCrawlerPage",
        *,
        label: str | None,
    ) -> None:
        self.page = page
        self.label = label

    def nth(self, _index: int):
        return self

    def locator(self, _selector: str):
        return self

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 1 if self.label else 0

    async def click(self, **_kwargs) -> None:
        if self.label == "权限管理":
            self.page.parent_expanded_via_locator = True
            return
        if self.label == "角色权限" and self.page.parent_expanded_via_locator:
            self.page.current_url = "https://erp.example.com/admin#/permission/role"
            self.page.current_title = "角色权限"

    async def dispatch_event(self, _event_name: str) -> None:
        await self.click()


class ParentLocatorExpansionRequiredFakeCrawlerPage(ClickDiscoverRouteFakeCrawlerPage):
    def __init__(self) -> None:
        super().__init__()
        self.parent_expanded_via_locator = False
        self.locator_click_labels: list[str] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        await super().goto(url, wait_until=wait_until)
        if "#/permission/role" not in url:
            self.parent_expanded_via_locator = False

    async def evaluate(self, script: str, *args):
        if "__RUNLET_CLICK_NAVIGATION_TARGET__" in script:
            target = dict(args[0]) if args and isinstance(args[0], dict) else {}
            self.click_targets.append(target)
            return {"clicked": False}
        return await super().evaluate(script, *args)

    def get_by_role(self, _role: str, **kwargs):
        label = kwargs.get("name")
        if isinstance(label, str):
            self.locator_click_labels.append(label)
        return ParentExpansionLocator(self, label=label if isinstance(label, str) else None)


class DelayedRouteChangeFakeCrawlerPage(ClickDiscoverRouteFakeCrawlerPage):
    def __init__(self) -> None:
        super().__init__()
        self.pending_route: str | None = None
        self.pending_title: str | None = None
        self.route_change_waits_remaining = 0

    async def evaluate(self, script: str, *args):
        if "__RUNLET_CLICK_NAVIGATION_TARGET__" in script:
            target = dict(args[0]) if args and isinstance(args[0], dict) else {}
            self.click_targets.append(target)
            if target.get("label") == "角色权限":
                self.pending_route = "https://erp.example.com/admin#/permission/role"
                self.pending_title = "角色权限"
                self.route_change_waits_remaining = 3
                return {"clicked": True}
            return {"clicked": False}
        return await super().evaluate(script, *args)

    async def wait_for_timeout(self, timeout: int) -> None:
        await super().wait_for_timeout(timeout)
        if timeout >= 250 and self.pending_route is not None:
            self.route_change_waits_remaining = max(0, self.route_change_waits_remaining - 1)
            if self.route_change_waits_remaining == 0:
                self.current_url = self.pending_route
                self.current_title = self.pending_title or self.current_title
                self.pending_route = None
                self.pending_title = None


class ClickDiscoveredDomElementsFakeCrawlerPage(ClickDiscoverRouteFakeCrawlerPage):
    async def evaluate(self, script: str, *args):
        if "__RUNLET_PAGE_ELEMENTS__" in script:
            parsed = urlparse(
                self.current_url
                if self.current_url.startswith("http")
                else "https://erp.example.com/admin#/dashboard"
            )
            if parsed.fragment == "/permission/role":
                return [
                    {
                        "page_route_path": "/admin",
                        "element_type": "button",
                        "role": "button",
                        "text": "新增角色",
                    }
                ]
            return []
        return await super().evaluate(script, *args)


class SingleFullRouteHintCollectionFakeCrawlerPage(ClickDiscoveredDomElementsFakeCrawlerPage):
    def __init__(self) -> None:
        super().__init__()
        self.route_hints_eval_calls = 0

    async def evaluate(self, script: str, *args):
        if "__RUNLET_ROUTE_HINTS__" in script:
            self.route_hints_eval_calls += 1
            if self.route_hints_eval_calls > 1:
                raise AssertionError("full route hints should be reused from cache")
        return await super().evaluate(script, *args)


class SingleFullMaterializedMenuCollectionFakeCrawlerPage(ClickDiscoveredDomElementsFakeCrawlerPage):
    def __init__(self) -> None:
        super().__init__()
        self.menu_nodes_eval_calls = 0
        self.materialize_eval_calls = 0

    async def evaluate(self, script: str, *args):
        if "__RUNLET_MENU_NODES__" in script:
            self.menu_nodes_eval_calls += 1
            if self.menu_nodes_eval_calls > 1:
                raise AssertionError("full materialized menu nodes should be reused from cache")
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            self.materialize_eval_calls += 1
            if self.materialize_eval_calls > 1:
                raise AssertionError("menu materialization should be reused from cache")
        return await super().evaluate(script, *args)


def install_materialize_aware_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    MaterializeAwareFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = MaterializeAwareFakeCrawlerPage()
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


def install_naive_collapsed_menu_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    NaiveCollapsedMenuFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = NaiveCollapsedMenuFakeCrawlerPage()
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


def install_click_discover_route_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    ClickDiscoverRouteFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = ClickDiscoverRouteFakeCrawlerPage()
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


def install_locator_fallback_missing_leaf_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    LocatorFallbackMissingLeafFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = LocatorFallbackMissingLeafFakeCrawlerPage()
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


def install_stale_js_click_then_locator_navigate_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    StaleJsClickThenLocatorNavigateFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = StaleJsClickThenLocatorNavigateFakeCrawlerPage()
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


def install_parent_locator_expansion_required_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    ParentLocatorExpansionRequiredFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = ParentLocatorExpansionRequiredFakeCrawlerPage()
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


def install_delayed_route_change_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DelayedRouteChangeFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = DelayedRouteChangeFakeCrawlerPage()
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


def install_click_discovered_dom_elements_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    ClickDiscoveredDomElementsFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = ClickDiscoveredDomElementsFakeCrawlerPage()
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


def install_single_full_route_hint_collection_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    SingleFullRouteHintCollectionFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = SingleFullRouteHintCollectionFakeCrawlerPage()
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


def install_single_full_materialized_menu_collection_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    SingleFullMaterializedMenuCollectionFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = SingleFullMaterializedMenuCollectionFakeCrawlerPage()
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


class RepeatedLabelMaterializeFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.materialize_calls: list[list[dict[str, object]]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/dashboard", "title": "仪表盘"}]
        if "__RUNLET_MENU_NODES__" in script:
            return [
                {
                    "label": "设置",
                    "route_path": "/system/roles",
                    "page_route_path": "/system/roles",
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "aria_label": "角色设置",
                    "entry_type": "menu_expand",
                    "aria_expanded": "false",
                },
                {
                    "label": "设置",
                    "route_path": "/system/admin",
                    "page_route_path": "/system/admin",
                    "depth": 0,
                    "order": 1,
                    "role": "menuitem",
                    "aria_label": "管理员设置",
                    "entry_type": "menu_expand",
                    "aria_expanded": "false",
                },
            ]
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            if any(
                target.get("route_path") == "/system/admin"
                and target.get("order") == 1
                and target.get("aria_label") == "管理员设置"
                for target in normalized_targets
            ):
                return [
                    {
                        "label": "管理员列表",
                        "route_path": "/system/admin/list",
                        "page_route_path": "/system/admin/list",
                        "depth": 1,
                        "order": 2,
                        "role": "menuitem",
                        "parent_label": "设置",
                    }
                ]
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
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


def install_repeated_label_materialize_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    RepeatedLabelMaterializeFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = RepeatedLabelMaterializeFakeCrawlerPage()
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


class RepeatedLabelNoRouteScriptAwareFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.materialize_calls: list[list[dict[str, object]]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/dashboard", "title": "仪表盘"}]
        if "__RUNLET_MENU_NODES__" in script:
            if "sibling_index" not in script:
                return [
                    {
                        "label": "设置",
                        "route_path": None,
                        "page_route_path": None,
                        "depth": 0,
                        "order": 0,
                        "role": "menuitem",
                        "entry_type": "menu_expand",
                        "aria_expanded": "false",
                    }
                ]
            return [
                {
                    "label": "设置",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                    "aria_expanded": "false",
                    "sibling_index": 0,
                },
                {
                    "label": "设置",
                    "route_path": None,
                    "page_route_path": None,
                    "depth": 0,
                    "order": 1,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                    "aria_expanded": "false",
                    "sibling_index": 1,
                },
            ]
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            if {target.get("sibling_index") for target in normalized_targets} == {0, 1}:
                return [
                    {
                        "label": "管理员列表",
                        "route_path": "/system/admin/list",
                        "page_route_path": "/system/admin/list",
                        "depth": 1,
                        "order": 0,
                        "role": "menuitem",
                        "parent_label": "设置",
                    }
                ]
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
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


def install_repeated_label_no_route_script_aware_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    RepeatedLabelNoRouteScriptAwareFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = RepeatedLabelNoRouteScriptAwareFakeCrawlerPage()
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


class HiddenDuplicateFindTargetFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.materialize_calls: list[list[dict[str, object]]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/dashboard", "title": "仪表盘"}]
        if "__RUNLET_MENU_NODES__" in script:
            return [
                {
                    "label": "设置",
                    "route_path": "/system/admin",
                    "page_route_path": "/system/admin",
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "entry_type": "menu_expand",
                    "sibling_index": 0,
                }
            ]
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            if (
                'if (!isVisible(node)) return null;' in script
                and any(target.get("sibling_index") == 0 for target in normalized_targets)
            ):
                return [
                    {
                        "label": "管理员列表",
                        "route_path": "/system/admin/list",
                        "page_route_path": "/system/admin/list",
                        "depth": 1,
                        "order": 0,
                        "role": "menuitem",
                        "parent_label": "设置",
                    }
                ]
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
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


def install_hidden_duplicate_find_target_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    HiddenDuplicateFindTargetFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = HiddenDuplicateFindTargetFakeCrawlerPage()
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


class DepthAwareFindTargetFakeCrawlerPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str]] = []
        self.wait_for_timeout_calls: list[int] = []
        self.closed = False
        self.settled = False
        self.current_url = "about:blank"
        self.materialize_calls: list[list[dict[str, object]]] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))
        self.current_url = url

    async def evaluate(self, script: str, *args):
        if "document.readyState" in script and "shell_ready" in script:
            return {"shell_ready": self.settled}
        if "visibleSelector" in script:
            return self.settled
        if "__RUNLET_ROUTE_SNAPSHOT__" in script:
            parsed = urlparse(self.current_url if self.current_url.startswith("http") else "https://erp.example.com/")
            return {
                "pathname": parsed.path or "/",
                "location_hash": f"#{parsed.fragment}" if parsed.fragment else None,
                "router_route": None,
                "history_route": None,
            }
        if "__RUNLET_ROUTE_HINTS__" in script:
            return [{"path": "/dashboard", "title": "仪表盘"}]
        if "__RUNLET_MENU_NODES__" in script:
            return [
                {
                    "label": "设置",
                    "route_path": "/system/root",
                    "page_route_path": "/system/root",
                    "depth": 0,
                    "order": 0,
                    "role": "menuitem",
                    "parent_label": "系统",
                    "entry_type": "menu_expand",
                    "sibling_index": 0,
                },
                {
                    "label": "设置",
                    "route_path": "/system/nested",
                    "page_route_path": "/system/nested",
                    "depth": 1,
                    "order": 1,
                    "role": "menuitem",
                    "parent_label": "系统",
                    "entry_type": "menu_expand",
                    "sibling_index": 0,
                },
            ]
        if "__RUNLET_MATERIALIZE_NAVIGATION_TARGETS__" in script:
            targets = args[0] if args else []
            normalized_targets = [dict(target) for target in targets if isinstance(target, dict)]
            self.materialize_calls.append(normalized_targets)
            if (
                "const targetDepth" in script
                and any(target.get("route_path") == "/system/nested" and target.get("depth") == 1 for target in normalized_targets)
            ):
                return [
                    {
                        "label": "深层设置",
                        "route_path": "/system/nested/detail",
                        "page_route_path": "/system/nested/detail",
                        "depth": 2,
                        "order": 0,
                        "role": "menuitem",
                        "parent_label": "设置",
                    }
                ]
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
        raise AssertionError(f"unexpected script: {script[:80]}")

    async def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)
        if timeout >= 5000:
            self.settled = True

    async def close(self) -> None:
        self.closed = True


def install_depth_aware_find_target_async_api(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DepthAwareFindTargetFakeCrawlerPage,
    FakeCrawlerContext,
    FakeCrawlerBrowser,
    FakeCrawlerChromium,
    FakeCrawlerPlaywright,
]:
    page = DepthAwareFindTargetFakeCrawlerPage()
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

    async def extract(
        self,
        *,
        browser_session,
        system,
        crawl_scope: str,
        page_candidates=None,
        navigation_targets=None,
    ) -> CrawlExtractionResult:
        del browser_session, system, crawl_scope, page_candidates, navigation_targets
        self.calls += 1
        return self.result


class SequencedExtractor:
    def __init__(self, *results: CrawlExtractionResult) -> None:
        self.results = list(results)
        self.calls = 0

    async def extract(self, **kwargs) -> CrawlExtractionResult:
        del kwargs
        self.calls += 1
        if not self.results:
            raise AssertionError("sequenced extractor exhausted")
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


class FakeAuthService:
    def __init__(
        self,
        *,
        db_session,
        system_id,
        base_url: str,
        result: AuthRefreshResult,
        refreshed_storage_state: dict[str, object] | None = None,
    ) -> None:
        self.db_session = db_session
        self.system_id = system_id
        self.base_url = base_url
        self.result = result
        self.refreshed_storage_state = refreshed_storage_state
        self.calls: list[object] = []

    async def refresh_auth_state(self, *, system_id):
        self.calls.append(system_id)
        if (
            self.result.status == "success"
            and self.refreshed_storage_state is not None
        ):
            refreshed_auth_state = AuthState(
                system_id=self.system_id,
                status=AuthStateStatus.VALID.value,
                storage_state=self.refreshed_storage_state,
                cookies={"items": self.refreshed_storage_state.get("cookies", [])},
                local_storage={
                    self.base_url: {
                        entry["name"]: entry["value"]
                        for origin in self.refreshed_storage_state.get("origins", [])
                        if origin.get("origin") == self.base_url
                        for entry in origin.get("localStorage", [])
                        if "name" in entry and "value" in entry
                    }
                },
                auth_mode="storage_state",
                is_valid=True,
                validated_at=datetime.now(UTC),
            )
            self.db_session.add(refreshed_auth_state)
            self.db_session.commit()
        return self.result


class PageVisitFirstBrowserSession:
    framework_hint = "react"

    def __init__(self) -> None:
        self.closed = False
        self.visited_routes: list[str] = []
        self.performed_targets: list[str] = []
        self.performed_payloads: list[dict[str, object]] = []
        self.page_contexts = {
            "/dashboard": {
                "route_path": "/dashboard",
                "resolved_route": "/dashboard",
                "state_context": {"active_tab": "default"},
                "elements": [
                    {
                        "page_route_path": "/dashboard",
                        "element_type": "button",
                        "role": "button",
                        "text": "刷新",
                    }
                ],
            },
            "/reports": {
                "route_path": "/reports",
                "resolved_route": "/reports",
                "state_context": {"active_tab": "default"},
                "elements": [
                    {
                        "page_route_path": "/reports",
                        "element_type": "button",
                        "role": "tab",
                        "text": "已归档",
                    }
                ],
            },
        }

    async def visit_page_target(
        self,
        *,
        page_target: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        del crawl_scope
        route_path = str(page_target.get("route_hint") or page_target.get("route_path") or "")
        self.visited_routes.append(route_path)
        context = self.page_contexts[route_path]
        return {
            "route_path": context["route_path"],
            "resolved_route": context["resolved_route"],
            "state_context": dict(context["state_context"]),
            "elements": [dict(element) for element in context["elements"]],
        }

    async def perform_navigation_target(
        self,
        *,
        target: dict[str, object],
        page_context: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        del crawl_scope, page_context
        self.performed_payloads.append(dict(target))
        entry_type = str(target.get("entry_type") or target.get("interaction_type") or "")
        self.performed_targets.append(entry_type)
        return {
            "route_path": "/reports",
            "state_context": {"active_tab": "已归档"},
            "elements": [
                {
                    "page_route_path": "/reports",
                    "element_type": "table",
                    "role": "grid",
                    "text": "归档报表",
                }
            ],
            "probe_applied": True,
        }

    async def close(self) -> None:
        self.closed = True


class PageVisitFirstBrowserFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.session = PageVisitFirstBrowserSession()

    async def open_context(
        self,
        *,
        base_url: str,
        storage_state: dict[str, object],
        entry_url: str | None = None,
    ) -> PageVisitFirstBrowserSession:
        self.calls.append(
            {
                "base_url": base_url,
                "storage_state": storage_state,
                "entry_url": entry_url,
            }
        )
        return self.session


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
            "entry_url": seeded_system.base_url,
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
async def test_run_crawl_defaults_snapshot_state_to_draft(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        router_extractor=FakeRouterExtractor(
            CrawlExtractionResult(
                framework_detected="react",
                pages=[PageCandidate(route_path="/users")],
            )
        ),
        dom_menu_extractor=FakeDomMenuExtractor(CrawlExtractionResult()),
    )

    result = await crawler_service.run_crawl(
        system_id=seeded_system.id,
        crawl_scope="full",
    )

    assert result.status == "success"

    snapshot = db_session.exec(select(CrawlSnapshot)).one()
    assert snapshot.state == "draft"
    assert snapshot.activated_at is None


@pytest.mark.anyio
async def test_run_crawl_passes_derived_entry_url_from_login_url(
    db_session,
    seeded_system,
    seeded_system_credentials,
    seeded_auth_state,
):
    seeded_system_credentials.login_url = "https://erp.example.com/admin#/login?redirect=/dashboard"
    db_session.add(seeded_system_credentials)
    db_session.commit()

    browser_factory = FakeBrowserFactory()
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=FakePageDiscoveryExtractor(CrawlExtractionResult()),
        dom_menu_extractor=FakeDomMenuExtractor(CrawlExtractionResult()),
        state_probe_extractor=FakeStateProbeExtractor(CrawlExtractionResult()),
    )

    result = await crawler_service.run_crawl(system_id=seeded_system.id, crawl_scope="full")

    assert result.status == "success"
    assert browser_factory.calls == [
        {
            "base_url": seeded_system.base_url,
            "storage_state": seeded_auth_state.storage_state,
            "entry_url": "https://erp.example.com/admin#/dashboard",
        }
    ]
    assert browser_factory.session.closed is True


@pytest.mark.anyio
async def test_run_crawl_persists_navigation_metadata_from_crawler_candidates(
    db_session,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            pages=[
                PageCandidate(
                    route_path="/users",
                    page_title="用户管理",
                    discovery_sources=["runtime_route_hints"],
                    navigation_diagnostics={
                        "resolved_route": "/users",
                        "route_source": "hash",
                        "warning_messages": ["route_stabilized"],
                    },
                )
            ],
        )
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[MenuCandidate(label="用户管理", route_path="/users", page_route_path="/users")]
        )
    )
    state_probe_extractor = FakeStateProbeExtractor(
        CrawlExtractionResult(
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="dialog",
                    state_signature="users:modal=create",
                    state_context={"entry_type": "open_modal", "modal_title": "新增用户"},
                    element_role="dialog",
                    element_text="新增用户",
                    playwright_locator="role=dialog[name='新增用户']",
                    locator_candidates=[
                        {"strategy_type": "semantic", "selector": "role=dialog[name='新增用户']"},
                    ],
                    materialized_by="open_modal",
                    navigation_diagnostics={
                        "target_kind": "open_modal",
                        "materialization_status": "applied",
                        "route_path": "/users",
                    },
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
    persisted_page = db_session.exec(select(Page).where(Page.route_path == "/users")).one()
    persisted_element = db_session.exec(select(PageElement)).one()
    assert persisted_page.navigation_diagnostics == {
        "resolved_route": "/users",
        "route_source": "hash",
        "warning_messages": ["route_stabilized"],
    }
    assert persisted_element.materialized_by == "open_modal"
    assert persisted_element.navigation_diagnostics == {
        "target_kind": "open_modal",
        "materialization_status": "applied",
        "route_path": "/users",
    }


@pytest.mark.anyio
async def test_run_crawl_persists_menu_parent_links_by_stable_identity(
    db_session,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            pages=[
                PageCandidate(route_path="/system/roles", page_title="角色设置"),
                PageCandidate(route_path="/system/roles/list", page_title="角色列表"),
                PageCandidate(route_path="/system/admin", page_title="管理员设置"),
                PageCandidate(route_path="/system/admin/list", page_title="管理员列表"),
            ],
        )
    )
    dom_menu_extractor = FakeDomMenuExtractor(
        CrawlExtractionResult(
            menus=[
                MenuCandidate(
                    label="设置",
                    route_path="/system/roles",
                    page_route_path="/system/roles",
                    navigation_identity={
                        "label": "设置",
                        "depth": 0,
                        "role": "menuitem",
                        "aria_label": "角色设置",
                        "sibling_index": 0,
                    },
                ),
                MenuCandidate(
                    label="设置",
                    route_path="/system/admin",
                    page_route_path="/system/admin",
                    navigation_identity={
                        "label": "设置",
                        "depth": 0,
                        "role": "menuitem",
                        "aria_label": "管理员设置",
                        "sibling_index": 1,
                    },
                ),
                MenuCandidate(
                    label="角色列表",
                    route_path="/system/roles/list",
                    page_route_path="/system/roles/list",
                    parent_label="设置",
                    navigation_identity={
                        "label": "角色列表",
                        "depth": 1,
                        "role": "menuitem",
                        "sibling_index": 0,
                    },
                    parent_navigation_identity={
                        "label": "设置",
                        "depth": 0,
                        "role": "menuitem",
                        "aria_label": "角色设置",
                        "sibling_index": 0,
                    },
                ),
                MenuCandidate(
                    label="管理员列表",
                    route_path="/system/admin/list",
                    page_route_path="/system/admin/list",
                    parent_label="设置",
                    navigation_identity={
                        "label": "管理员列表",
                        "depth": 1,
                        "role": "menuitem",
                        "sibling_index": 0,
                    },
                    parent_navigation_identity={
                        "label": "设置",
                        "depth": 0,
                        "role": "menuitem",
                        "aria_label": "管理员设置",
                        "sibling_index": 1,
                    },
                ),
            ]
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=FakeStateProbeExtractor(CrawlExtractionResult()),
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    menus = db_session.exec(select(MenuNode).order_by(MenuNode.sort_order, MenuNode.id)).all()
    by_route = {menu.route_path: menu for menu in menus}
    assert by_route["/system/roles/list"].parent_id == by_route["/system/roles"].id
    assert by_route["/system/admin/list"].parent_id == by_route["/system/admin"].id


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
async def test_run_crawl_refreshes_stale_auth_state_once_and_retries_successfully(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    refreshed_storage_state = {
        "cookies": [{"name": "sid", "value": "refreshed-456"}],
        "origins": [
            {
                "origin": seeded_system.base_url,
                "localStorage": [{"name": "token", "value": "refreshed-token"}],
            }
        ],
    }
    auth_service = FakeAuthService(
        db_session=db_session,
        system_id=seeded_system.id,
        base_url=seeded_system.base_url,
        result=AuthRefreshResult(
            system_id=seeded_system.id,
            status="success",
            validated_at=datetime.now(UTC),
        ),
        refreshed_storage_state=refreshed_storage_state,
    )
    page_discovery_extractor = SequencedExtractor(
        CrawlExtractionResult(
            pages=[PageCandidate(route_path="/front/login", page_title="登录页")],
        ),
        CrawlExtractionResult(
            pages=[PageCandidate(route_path="/dashboard", page_title="仪表盘")],
        ),
    )
    dom_menu_extractor = SequencedExtractor(
        CrawlExtractionResult(),
        CrawlExtractionResult(
            menus=[
                MenuCandidate(
                    label="仪表盘",
                    route_path="/dashboard",
                    page_route_path="/dashboard",
                )
            ]
        ),
    )
    state_probe_extractor = SequencedExtractor(
        CrawlExtractionResult(
                elements=[
                    ElementCandidate(
                        page_route_path="/front/login",
                        element_type="input",
                        state_signature="/front/login|default",
                        element_text="用户名",
                    )
                ],
            warning_messages=["state_probe_baseline_degraded"],
            degraded=True,
        ),
        CrawlExtractionResult(
                elements=[
                    ElementCandidate(
                        page_route_path="/dashboard",
                        element_type="button",
                        state_signature="/dashboard|default",
                        element_role="button",
                        element_text="刷新",
                        playwright_locator="role=button[name='刷新']",
                )
            ]
        ),
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        auth_service=auth_service,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=dom_menu_extractor,
        state_probe_extractor=state_probe_extractor,
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert auth_service.calls == [seeded_auth_state.system_id]
    assert result.status == "success"
    assert result.pages_saved == 1
    assert result.menus_saved == 1
    assert result.elements_saved == 1
    assert "auth_state_auto_refreshed" in result.warning_messages
    assert browser_factory.calls == [
        {
            "base_url": seeded_system.base_url,
            "storage_state": seeded_auth_state.storage_state,
            "entry_url": seeded_system.base_url,
        },
        {
            "base_url": seeded_system.base_url,
            "storage_state": refreshed_storage_state,
            "entry_url": seeded_system.base_url,
        },
    ]
    snapshots = db_session.exec(select(CrawlSnapshot)).all()
    assert len(snapshots) == 1
    pages = db_session.exec(select(Page).order_by(Page.route_path, Page.id)).all()
    assert [page.route_path for page in pages] == ["/dashboard"]


@pytest.mark.anyio
async def test_run_crawl_returns_initial_result_when_auth_refresh_fails(
    db_session,
    seeded_system,
    seeded_auth_state,
):
    browser_factory = FakeBrowserFactory()
    auth_service = FakeAuthService(
        db_session=db_session,
        system_id=seeded_system.id,
        base_url=seeded_system.base_url,
        result=AuthRefreshResult(
            system_id=seeded_system.id,
            status="failed",
            message="login failed",
        ),
    )
    stale_discovery = CrawlExtractionResult(
        pages=[PageCandidate(route_path="/front/login", page_title="登录页")],
    )
    stale_probe = CrawlExtractionResult(
        elements=[
            ElementCandidate(
                page_route_path="/front/login",
                element_type="button",
                state_signature="/front/login|default",
                element_text="登录",
            )
        ],
        warning_messages=["state_probe_baseline_degraded"],
        degraded=True,
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        auth_service=auth_service,
        page_discovery_extractor=FakePageDiscoveryExtractor(stale_discovery),
        dom_menu_extractor=FakeDomMenuExtractor(CrawlExtractionResult()),
        state_probe_extractor=FakeStateProbeExtractor(stale_probe),
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert auth_service.calls == [seeded_auth_state.system_id]
    assert result.status == "success"
    assert result.pages_saved == 1
    assert result.menus_saved == 0
    assert result.elements_saved == 1
    assert "auth_state_refresh_failed" in result.warning_messages
    assert result.message == "login failed"
    assert browser_factory.calls == [
        {
            "base_url": seeded_system.base_url,
            "storage_state": seeded_auth_state.storage_state,
            "entry_url": seeded_system.base_url,
        }
    ]
    snapshots = db_session.exec(select(CrawlSnapshot)).all()
    assert len(snapshots) == 1
    pages = db_session.exec(select(Page).order_by(Page.route_path, Page.id)).all()
    assert [page.route_path for page in pages] == ["/front/login"]


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
async def test_hotgo_like_session_yields_non_root_pages_and_menu_nodes(
    monkeypatch: pytest.MonkeyPatch,
    db_session,
    seeded_system,
    seeded_auth_state,
):
    page, context, browser, chromium, playwright = install_hotgo_like_async_api(monkeypatch)
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=PlaywrightBrowserFactory(),
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    pages = db_session.exec(select(Page).order_by(Page.route_path, Page.id)).all()
    menus = db_session.exec(select(MenuNode).order_by(MenuNode.sort_order, MenuNode.id)).all()
    elements = db_session.exec(select(PageElement).order_by(PageElement.id)).all()
    page_routes = [item.route_path for item in pages]
    root_menu_routes = [item.route_path for item in menus if item.parent_id is None]
    child_menus = [item for item in menus if item.parent_id is not None]

    assert result.status == "success"
    assert result.pages_saved >= 3
    assert result.menus_saved >= 2
    assert result.elements_saved >= 2
    assert page_routes == ["/dashboard", "/system/users", "/workbench"]
    assert [hint["path"] for hint in page.route_hints] == ["/dashboard", "/workbench"]
    assert page.skeleton_menu_routes == ["/dashboard", "/workbench"]
    assert "/system/users" not in root_menu_routes
    assert any(menu.label == "系统管理" and menu.route_path is None for menu in menus)
    assert len(child_menus) == 1
    assert child_menus[0].label == "用户管理"
    assert child_menus[0].route_path == "/system/users"
    assert page.materialize_calls
    assert all(len(call) == 1 for call in page.materialize_calls)
    assert all(call[0]["target_kind"] == "menu_expand" for call in page.materialize_calls)
    assert all(call[0]["label"] == "系统管理" for call in page.materialize_calls)
    assert all(call[0]["route_path"] is None for call in page.materialize_calls)
    assert all(call[0]["page_route_path"] is None for call in page.materialize_calls)
    assert page.route_snapshot_eval_calls >= 4
    assert page.readiness_shell_eval_calls >= 4
    assert page.wait_for_timeout_calls[0] == 5000
    assert page.wait_for_timeout_calls.count(2000) >= 3
    assert page.goto_calls[0] == ("https://erp.example.com", "domcontentloaded")
    assert ("https://erp.example.com/system/users", "domcontentloaded") in page.goto_calls
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True
    assert len(elements) == result.elements_saved


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
async def test_collect_dom_menu_nodes_materializes_children_after_expand(monkeypatch):
    page, context, browser, chromium, playwright = install_materialize_aware_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    await session.close()

    assert {node["label"] for node in menu_nodes} >= {"权限管理", "管理员列表"}
    assert any(
        node.get("parent_label") == "权限管理" and node.get("label") == "管理员列表"
        for node in menu_nodes
    )
    assert page.materialize_calls
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_menu_nodes_materializes_naive_collapsed_menu_items(monkeypatch):
    page, context, browser, chromium, playwright = install_naive_collapsed_menu_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    await session.close()

    assert {node["label"] for node in menu_nodes} >= {"权限管理", "角色权限"}
    assert any(
        node.get("label") == "权限管理" and node.get("entry_type") == "menu_expand"
        for node in menu_nodes
    )
    assert any(
        node.get("label") == "角色权限" and node.get("parent_label") == "权限管理"
        for node in menu_nodes
    )
    assert len(page.materialize_calls) == 1
    assert page.materialize_calls[0][0]["target_kind"] == "menu_expand"
    assert page.materialize_calls[0][0]["label"] == "权限管理"
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_playwright_browser_factory_collects_dom_elements_from_materialized_submenu_routes(monkeypatch):
    page, context, browser, chromium, playwright = install_materialize_aware_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert dom_elements == [
        {
            "page_route_path": "/system/admin",
            "element_type": "button",
            "role": "button",
            "text": "新增管理员",
        }
    ]
    assert page.materialize_calls
    assert ("https://erp.example.com/system/admin", "domcontentloaded") in page.goto_calls
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_route_hints_discovers_routes_by_clicking_route_less_leaf_menus(monkeypatch):
    page, context, browser, chromium, playwright = install_click_discover_route_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert {hint["path"] for hint in route_hints} >= {"/admin", "/permission/role"}
    discovered_hint = next(hint for hint in route_hints if hint["path"] == "/permission/role")
    assert discovered_hint["title"] == "角色权限"
    assert len(page.materialize_calls) == 1
    assert [target["label"] for target in page.click_targets] == ["权限管理", "角色权限"]
    assert page.click_targets[-1]["parent_label"] == "权限管理"
    assert page.click_targets[-1]["depth"] == 1
    assert page.click_targets[-1]["role"] == "menuitem"
    assert page.goto_calls == [
        ("https://erp.example.com/admin#/dashboard", "domcontentloaded"),
        ("https://erp.example.com/admin#/dashboard", "domcontentloaded"),
    ]
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_route_hints_skips_missing_leaf_when_locator_fallback_has_no_match(monkeypatch):
    page, context, browser, chromium, playwright = install_locator_fallback_missing_leaf_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert route_hints == [{"path": "/admin", "title": "主控台"}]
    assert page.click_targets == []
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_route_hints_falls_back_to_locator_when_js_click_does_not_change_route(monkeypatch):
    page, context, browser, chromium, playwright = install_stale_js_click_then_locator_navigate_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert {hint["path"] for hint in route_hints} >= {"/admin", "/permission/role"}
    discovered_hint = next(hint for hint in route_hints if hint["path"] == "/permission/role")
    assert discovered_hint["title"] == "角色权限"
    assert len(page.click_targets) == 1
    assert page.click_targets[0]["label"] == "角色权限"
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_route_hints_expands_parent_chain_before_clicking_route_less_leaf(monkeypatch):
    page, context, browser, chromium, playwright = install_parent_locator_expansion_required_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert {hint["path"] for hint in route_hints} >= {"/admin", "/permission/role"}
    discovered_hint = next(hint for hint in route_hints if hint["path"] == "/permission/role")
    assert discovered_hint["title"] == "角色权限"
    assert page.locator_click_labels[:2] == ["权限管理", "角色权限"]
    assert len(page.materialize_calls) == 1
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_route_hints_waits_for_delayed_route_change_after_leaf_click(monkeypatch):
    page, context, browser, chromium, playwright = install_delayed_route_change_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    await session.close()

    assert {hint["path"] for hint in route_hints} >= {"/admin", "/permission/role"}
    assert any(timeout == 250 for timeout in page.wait_for_timeout_calls)
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_elements_uses_click_discovered_route_hints_for_route_less_leaf(monkeypatch):
    page, context, browser, chromium, playwright = install_click_discovered_dom_elements_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert dom_elements == [
        {
            "page_route_path": "/permission/role",
            "element_type": "button",
            "role": "button",
            "text": "新增角色",
        }
    ]
    assert ("https://erp.example.com/admin#/permission/role", "domcontentloaded") in page.goto_calls
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_elements_reuses_full_route_hints_after_prior_full_route_collection(monkeypatch):
    page, context, browser, chromium, playwright = install_single_full_route_hint_collection_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    route_hints = await session.collect_route_hints(crawl_scope="full")
    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert any(hint["path"] == "/permission/role" for hint in route_hints)
    assert dom_elements == [
        {
            "page_route_path": "/permission/role",
            "element_type": "button",
            "role": "button",
            "text": "新增角色",
        }
    ]
    assert page.route_hints_eval_calls == 1
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_elements_reuses_full_materialized_menu_nodes_after_prior_full_menu_collection(monkeypatch):
    page, context, browser, chromium, playwright = install_single_full_materialized_menu_collection_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert any(node["label"] == "角色权限" for node in menu_nodes)
    assert dom_elements == [
        {
            "page_route_path": "/permission/role",
            "element_type": "button",
            "role": "button",
            "text": "新增角色",
        }
    ]
    assert page.menu_nodes_eval_calls == 1
    assert page.materialize_eval_calls == 1
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


def test_merge_menu_skeleton_and_materialized_nodes_merges_route_back_into_placeholder():
    merged = merge_menu_skeleton_and_materialized_nodes(
        skeleton=[
            {
                "label": "权限管理",
                "route_path": None,
                "page_route_path": None,
                "depth": 0,
                "order": 0,
                "role": "menuitem",
            }
        ],
        materialized=[
            {
                "label": "权限管理",
                "route_path": "/system/admin",
                "page_route_path": "/system/admin",
                "depth": 0,
                "order": 0,
                "role": "menuitem",
            }
        ],
    )

    assert len(merged) == 1
    assert merged[0]["label"] == "权限管理"
    assert merged[0]["route_path"] == "/system/admin"
    assert merged[0]["page_route_path"] == "/system/admin"


def test_merge_menu_skeleton_and_materialized_nodes_preserves_repeated_label_siblings():
    merged = merge_menu_skeleton_and_materialized_nodes(
        skeleton=[
            {
                "label": "设置",
                "route_path": None,
                "page_route_path": None,
                "depth": 0,
                "order": 0,
                "role": "menuitem",
                "aria_label": "角色设置",
            },
            {
                "label": "设置",
                "route_path": None,
                "page_route_path": None,
                "depth": 0,
                "order": 1,
                "role": "menuitem",
                "aria_label": "管理员设置",
            },
        ],
        materialized=[
            {
                "label": "设置",
                "route_path": "/system/roles",
                "page_route_path": "/system/roles",
                "depth": 0,
                "order": 0,
                "role": "menuitem",
                "aria_label": "角色设置",
            },
            {
                "label": "设置",
                "route_path": "/system/admin",
                "page_route_path": "/system/admin",
                "depth": 0,
                "order": 1,
                "role": "menuitem",
                "aria_label": "管理员设置",
            },
        ],
    )

    assert len(merged) == 2
    assert [(item["order"], item["route_path"], item["aria_label"]) for item in merged] == [
        (0, "/system/roles", "角色设置"),
        (1, "/system/admin", "管理员设置"),
    ]


def test_merge_menu_skeleton_and_materialized_nodes_replaces_stale_route_with_better_fact():
    merged = merge_menu_skeleton_and_materialized_nodes(
        skeleton=[
            {
                "label": "设置",
                "route_path": "/system/stale",
                "page_route_path": "/system/stale",
                "depth": 0,
                "order": 1,
                "role": "menuitem",
                "aria_label": "管理员设置",
            }
        ],
        materialized=[
            {
                "label": "设置",
                "route_path": "/system/admin",
                "page_route_path": "/system/admin",
                "depth": 0,
                "order": 1,
                "role": "menuitem",
                "aria_label": "管理员设置",
            }
        ],
    )

    assert len(merged) == 1
    assert merged[0]["route_path"] == "/system/admin"
    assert merged[0]["page_route_path"] == "/system/admin"


def test_merge_menu_skeleton_and_materialized_nodes_replaces_stale_route_even_when_order_differs():
    merged = merge_menu_skeleton_and_materialized_nodes(
        skeleton=[
            {
                "label": "设置",
                "route_path": "/system/stale",
                "page_route_path": "/system/stale",
                "depth": 0,
                "order": 9,
                "role": "menuitem",
                "sibling_index": 1,
            }
        ],
        materialized=[
            {
                "label": "设置",
                "route_path": "/system/admin",
                "page_route_path": "/system/admin",
                "depth": 0,
                "order": 0,
                "role": "menuitem",
                "sibling_index": 1,
            }
        ],
    )

    assert len(merged) == 1
    assert merged[0]["route_path"] == "/system/admin"
    assert merged[0]["page_route_path"] == "/system/admin"


@pytest.mark.anyio
async def test_collect_dom_menu_nodes_materializes_repeated_label_target_using_route_and_order_hints(monkeypatch):
    page, context, browser, chromium, playwright = install_repeated_label_materialize_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    await session.close()

    assert {node["label"] for node in menu_nodes} >= {"设置", "管理员列表"}
    assert any(node.get("route_path") == "/system/admin/list" for node in menu_nodes)
    assert len(page.materialize_calls) == 1
    assert [(target.get("order"), target.get("route_path"), target.get("aria_label")) for target in page.materialize_calls[0]] == [
        (0, "/system/roles", "角色设置"),
        (1, "/system/admin", "管理员设置"),
    ]
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_menu_nodes_preserves_repeated_label_siblings_without_routes(monkeypatch):
    page, context, browser, chromium, playwright = install_repeated_label_no_route_script_aware_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    await session.close()

    assert [node["label"] for node in menu_nodes].count("设置") == 2
    assert {node.get("sibling_index") for node in menu_nodes if node["label"] == "设置"} == {0, 1}
    assert any(node.get("route_path") == "/system/admin/list" for node in menu_nodes)
    assert len(page.materialize_calls) == 1
    assert {target.get("sibling_index") for target in page.materialize_calls[0]} == {0, 1}
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_menu_nodes_materialize_matches_visible_sibling_index_when_hidden_duplicate_exists(monkeypatch):
    page, context, browser, chromium, playwright = install_hidden_duplicate_find_target_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    await session.close()

    assert any(node.get("route_path") == "/system/admin/list" for node in menu_nodes)
    assert len(page.materialize_calls) == 1
    assert page.materialize_calls[0][0].get("sibling_index") == 0
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_menu_nodes_materialize_matches_target_depth(monkeypatch):
    page, context, browser, chromium, playwright = install_depth_aware_find_target_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    menu_nodes = await session.collect_dom_menu_nodes(crawl_scope="full")
    await session.close()

    assert any(node.get("route_path") == "/system/nested/detail" for node in menu_nodes)
    assert len(page.materialize_calls) == 1
    assert any(target.get("route_path") == "/system/nested" and target.get("depth") == 1 for target in page.materialize_calls[0])
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
async def test_playwright_browser_factory_rechecks_readiness_after_secondary_page_visits(monkeypatch):
    page, context, browser, chromium, playwright = install_per_visit_readiness_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert [element["page_route_path"] for element in dom_elements] == ["/dashboard", "/users"]
    assert "/" in page.readiness_shell_urls
    assert "/dashboard" in page.readiness_shell_urls
    assert "/users" in page.readiness_shell_urls
    assert page.route_ready_urls.count("/dashboard") >= 1
    assert page.route_ready_urls.count("/users") >= 1
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_elements_current_scope_prefers_resolved_hash_route(monkeypatch):
    page, context, browser, chromium, playwright = install_hash_route_current_scope_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="current")
    await session.close()

    assert dom_elements == [
        {
            "page_route_path": "/users",
            "element_type": "button",
            "role": "button",
            "text": "新增用户",
        }
    ]
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


@pytest.mark.anyio
async def test_collect_dom_elements_full_scope_uses_entry_hash_shell_for_hash_routes(monkeypatch):
    page, context, browser, chromium, playwright = install_hash_route_full_scope_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()

    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
        entry_url="https://erp.example.com/admin#/dashboard",
    )

    dom_elements = await session.collect_dom_elements(crawl_scope="full")
    await session.close()

    assert dom_elements == [
        {
            "page_route_path": "/dashboard/console",
            "element_type": "button",
            "role": "button",
            "text": "刷新主控台",
        },
        {
            "page_route_path": "/permission/role",
            "element_type": "table",
            "role": "grid",
            "text": "角色权限表格",
        },
    ]
    assert page.goto_calls == [
        ("https://erp.example.com/admin#/dashboard", "domcontentloaded"),
        ("https://erp.example.com/admin#/dashboard/console", "domcontentloaded"),
        ("https://erp.example.com/admin#/permission/role", "domcontentloaded"),
    ]
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


@pytest.mark.anyio
async def test_run_crawl_discovers_page_before_state_probe_targets(
    db_session,
    seeded_auth_state,
):
    browser_factory = PageVisitFirstBrowserFactory()
    page_discovery_extractor = FakePageDiscoveryExtractor(
        CrawlExtractionResult(
            pages=[
                PageCandidate(route_path="/dashboard", page_title="仪表盘", discovery_sources=["runtime_route_hints"]),
                PageCandidate(route_path="/reports", page_title="报表中心", discovery_sources=["network_route_config"]),
            ]
        )
    )
    crawler_service = CrawlerService(
        session=db_session,
        browser_factory=browser_factory,
        page_discovery_extractor=page_discovery_extractor,
        dom_menu_extractor=FakeDomMenuExtractor(CrawlExtractionResult()),
    )

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.status == "success"
    assert result.pages_saved >= 2
    assert result.elements_saved >= 2
    assert "route_unresolved" not in result.warning_messages
    assert browser_factory.session.visited_routes == ["/dashboard", "/reports"]
    assert browser_factory.session.performed_targets == ["tab_switch"]
    assert browser_factory.session.performed_payloads[0]["entry_type"] == "tab_switch"
    assert browser_factory.session.performed_payloads[0]["interaction_type"] == "tab_switch"


@pytest.mark.anyio
async def test_page_first_state_probe_uses_real_execution_contract_with_entry_type(monkeypatch):
    page, context, browser, chromium, playwright = install_state_probe_aware_async_api(monkeypatch)
    factory = PlaywrightBrowserFactory()
    session = await factory.open_context(
        base_url="https://erp.example.com",
        storage_state={"cookies": [{"name": "sid", "value": "abc123"}]},
    )

    result = await ControlledStateProbeExtractor().extract(
        browser_session=session,
        system=None,
        crawl_scope="full",
        page_candidates=[PageCandidate(route_path="/users", page_title="用户管理")],
        navigation_targets=[
            {
                "target_key": "tab:/users/disabled",
                "target_kind": "tab_switch",
                "route_hint": "/users",
                "parent_target_key": "page:/users",
                "state_context": {"active_tab": "disabled"},
                "materialization_status": "queued",
            }
        ],
    )
    await session.close()

    assert "users:tab=disabled" in {element.state_signature for element in result.elements}
    assert "tab_switch" in page.executed_probe_actions
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True
