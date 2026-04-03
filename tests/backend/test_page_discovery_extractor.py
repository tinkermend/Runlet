import pytest

from app.domains.crawler_service.extractors.page_discovery import PageDiscoveryExtractor


class FakeDiscoverySession:
    framework_hint = "react"

    def __init__(self) -> None:
        self.route_hints = [
            {"path": "/dashboard", "title": "仪表盘"},
            {"path": "/users", "title": "用户管理"},
        ]
        self.dom_menu_nodes = [
            {"label": "用户管理", "route_path": "/users", "role": "menuitem"},
            {"label": "报表中心", "route_path": "/reports", "role": "menuitem"},
            {
                "label": "用户标签页",
                "page_route_path": "/users",
                "entry_type": "tab_switch",
                "role": "tab",
            },
            {
                "label": "新增用户",
                "page_route_path": "/users",
                "entry_type": "open_modal",
                "role": "button",
            },
        ]
        self.network_route_configs = [
            {"route_path": "/reports", "source": "webpack-route-manifest"},
            {"path": "/users", "source": "xhr-preload"},
        ]

    async def collect_route_hints(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return self.route_hints

    async def collect_dom_menu_nodes(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return self.dom_menu_nodes

    async def collect_network_route_configs(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return self.network_route_configs


@pytest.mark.anyio
async def test_page_discovery_merges_route_nav_and_network_signals():
    extractor = PageDiscoveryExtractor()
    result = await extractor.extract(browser_session=FakeDiscoverySession(), system=None, crawl_scope="full")

    assert {page.route_path for page in result.pages} >= {"/dashboard", "/users", "/reports"}
    assert any("network_route_config" in page.discovery_sources for page in result.pages)


@pytest.mark.anyio
async def test_page_discovery_marks_tabs_and_modal_triggers_as_entry_candidates():
    result = await PageDiscoveryExtractor().extract(
        browser_session=FakeDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    users_page = next(page for page in result.pages if page.route_path == "/users")
    assert {"tab_switch", "open_modal"} <= {entry["entry_type"] for entry in users_page.entry_candidates}


@pytest.mark.anyio
async def test_page_discovery_merges_duplicate_page_sources():
    result = await PageDiscoveryExtractor().extract(
        browser_session=FakeDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    users_page = next(page for page in result.pages if page.route_path == "/users")
    assert set(users_page.discovery_sources) >= {"runtime_route_hints", "dom_menu_tree", "network_route_config"}
