import sys
from types import ModuleType

import pytest
from sqlmodel import select

from app.domains.crawler_service.schemas import (
    CrawlExtractionResult,
    ElementCandidate,
    MenuCandidate,
    PageCandidate,
)
from app.domains.crawler_service.service import CrawlerService, PlaywrightBrowserFactory
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement


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
        self.closed = False

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append((url, wait_until))

    async def evaluate(self, script: str):
        if "__RUNLET_ROUTE_HINTS__" in script:
            assert "__NEXT_DATA__" in script
            assert "__NUXT__" in script
            assert "__VUE_ROUTER__" in script
            return [
                {"path": "/dashboard", "title": "仪表盘"},
                {"path": "/users", "title": "用户管理"},
            ]
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
        raise AssertionError(f"unexpected script: {script[:80]}")

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
                )
            ],
            elements=[
                ElementCandidate(
                    page_route_path="/users",
                    element_type="button",
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
    assert len(menus) == 1
    assert menus[0].playwright_locator == "role=menuitem[name='用户管理']"
    assert len(elements) == 1
    assert elements[0].playwright_locator == "role=button[name='新增用户']"


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
    await session.close()

    assert route_hints[0]["path"] == "/dashboard"
    assert menu_nodes[1]["label"] == "用户管理"
    assert dom_elements[0]["element_type"] == "button"
    assert page.goto_calls == [("https://erp.example.com", "domcontentloaded")]
    assert chromium.headless_calls == [True]
    assert page.closed is True
    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True
