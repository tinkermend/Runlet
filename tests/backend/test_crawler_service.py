import pytest
from sqlmodel import select

from app.domains.crawler_service.schemas import (
    CrawlExtractionResult,
    ElementCandidate,
    MenuCandidate,
    PageCandidate,
)
from app.domains.crawler_service.service import CrawlerService
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement


class FakeBrowserSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


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
