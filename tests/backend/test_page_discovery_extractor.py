import pytest

from app.domains.crawler_service.extractors.page_discovery import PageDiscoveryExtractor


class FakeDomMenuExtractor:
    def __init__(self, signals: list[dict[str, object]]) -> None:
        self._signals = signals

    async def collect_navigation_signals(self, *, browser_session, crawl_scope: str) -> list[dict[str, object]]:
        del browser_session, crawl_scope
        return [dict(signal) for signal in self._signals]


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
                "route_path": "/users/tab/security",
                "page_route_path": "/users",
                "entry_type": "tab_switch",
                "role": "tab",
            },
            {
                "label": "新增用户",
                "route_path": "/users/modal/create",
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


class NetworkFailureDiscoverySession(FakeDiscoverySession):
    async def collect_network_route_configs(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        raise RuntimeError("network collector unavailable")


class NetworkSignalDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.route_hints = [{"path": "/dashboard", "title": "仪表盘"}]
        self.network_route_configs = []
        self.network_resource_hints_calls = 0
        self.network_requests_calls = 0
        self.network_resource_hints = [{"route_path": "/reports"}]
        self.network_requests = [{"path": "/users"}]

    async def collect_network_resource_hints(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        self.network_resource_hints_calls += 1
        return self.network_resource_hints

    async def collect_network_requests(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        self.network_requests_calls += 1
        return self.network_requests


class MetadataFailureDiscoverySession(FakeDiscoverySession):
    async def collect_page_metadata(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        raise RuntimeError("metadata collector unavailable")


class PartialNetworkFailureDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.route_hints = [{"path": "/dashboard", "title": "仪表盘"}]
        self.dom_menu_nodes = [{"label": "用户管理", "route_path": "/users", "role": "menuitem"}]
        self.network_route_config_calls = 0
        self.network_resource_hints_calls = 0
        self.network_requests_calls = 0

    async def collect_network_route_configs(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        self.network_route_config_calls += 1
        raise RuntimeError("network route config unavailable")

    async def collect_network_resource_hints(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        self.network_resource_hints_calls += 1
        return [{"route_path": "/reports"}]

    async def collect_network_requests(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        self.network_requests_calls += 1
        return [{"path": "/alerts"}]


class MetadataEnrichmentDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.route_hints = [{"path": "/users", "title": "用户管理"}]
        self.dom_menu_nodes = []
        self.network_route_configs = []

    async def collect_page_metadata(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return [
            {
                "route_path": "/users",
                "page_title": "用户管理-元数据",
                "reachable": True,
                "status_code": 200,
            },
            {
                "route_path": "/metadata-only",
                "page_title": "仅元数据页面",
                "reachable": True,
                "status_code": 200,
            },
        ]


class DuplicateInteractionDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.dom_menu_nodes.extend(
            [
                {
                    "label": "用户标签页",
                    "route_path": "/users/tab/security",
                    "page_route_path": "/users",
                    "entry_type": "tab_switch",
                    "role": "tab",
                    "source": "secondary-dom-scan",
                },
                {
                    "label": "用户标签页",
                    "route_path": "/users/tab/security",
                    "page_route_path": "/users",
                    "entry_type": "tab_switch",
                    "role": "tab",
                    "source": "tertiary-dom-scan",
                },
            ]
        )


class RichInteractionDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.dom_menu_nodes.extend(
            [
                {
                    "label": "切换为卡片视图",
                    "page_route_path": "/users",
                    "entry_type": "toggle_view",
                    "role": "button",
                },
                {
                    "label": "展开高级筛选",
                    "page_route_path": "/users",
                    "entry_type": "expand_panel",
                    "role": "button",
                },
            ]
        )


class RouteBudgetDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.dom_menu_nodes = [
            {
                "label": "启用用户",
                "page_route_path": "/users",
                "entry_type": "toggle_view",
                "role": "button",
            },
            {
                "label": "展开高级筛选",
                "page_route_path": "/users",
                "entry_type": "expand_panel",
                "role": "button",
            },
        ]
        self.route_hints = [{"path": "/users", "title": "用户管理"}]
        self.network_route_configs = []


class PrioritySourceDiscoverySession(FakeDiscoverySession):
    def __init__(self) -> None:
        super().__init__()
        self.route_hints = []
        self.network_route_configs = []
        self.dom_menu_nodes = [
            {
                "label": "用户标签页",
                "route_path": "/users/tab/security",
                "page_route_path": "/users",
                "entry_type": "tab_switch",
                "role": "tab",
                "discovery_sources": ["network_request", "runtime_route_hints"],
            }
        ]


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
    assert "/users/tab/security" not in {page.route_path for page in result.pages}
    assert "/users/modal/create" not in {page.route_path for page in result.pages}


@pytest.mark.anyio
async def test_page_discovery_emits_navigation_targets_before_materializing_pages():
    result = await PageDiscoveryExtractor().extract(
        browser_session=FakeDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    assert {"page_route", "tab_switch", "open_modal"} <= {
        target.target_kind for target in result.navigation_targets
    }
    users_tab = next(
        target
        for target in result.navigation_targets
        if target.target_kind == "tab_switch" and target.parent_target_key == "page:/users"
    )
    create_modal = next(
        target
        for target in result.navigation_targets
        if target.target_kind == "open_modal" and target.parent_target_key == "page:/users"
    )

    assert users_tab.route_hint == "/users"
    assert users_tab.state_context is not None
    assert users_tab.state_context["active_tab"] == "用户标签页"
    assert create_modal.state_context is not None
    assert create_modal.state_context["modal_title"] == "新增用户"
    assert all(target.materialization_status == "queued" for target in result.navigation_targets)


@pytest.mark.anyio
async def test_page_discovery_preserves_toggle_view_and_expand_panel_targets():
    result = await PageDiscoveryExtractor().extract(
        browser_session=RichInteractionDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    users_targets = {
        target.target_kind: target
        for target in result.navigation_targets
        if target.parent_target_key == "page:/users"
    }

    assert "toggle_view" in users_targets
    assert "expand_panel" in users_targets
    assert users_targets["toggle_view"].state_context == {"view_mode": "切换为卡片视图"}
    assert users_targets["expand_panel"].state_context == {"panel_title": "展开高级筛选"}


@pytest.mark.anyio
async def test_page_discovery_prefers_source_priority_for_navigation_target_primary_source():
    extractor = PageDiscoveryExtractor(
        dom_menu_extractor=FakeDomMenuExtractor(
            [
                {
                    "label": "用户标签页",
                    "route_path": "/users/tab/security",
                    "page_route_path": "/users",
                    "entry_type": "tab_switch",
                    "discovery_sources": ["network_request", "runtime_route_hints", "dom_menu_tree"],
                }
            ]
        )
    )
    result = await extractor.extract(
        browser_session=PrioritySourceDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    target = next(
        target for target in result.navigation_targets if target.target_kind == "tab_switch"
    )
    assert target.discovery_source == "runtime_route_hints"


@pytest.mark.anyio
async def test_page_discovery_surfaces_budget_rejected_targets_in_navigation_diagnostics():
    result = await PageDiscoveryExtractor(max_targets_per_route=1).extract(
        browser_session=RouteBudgetDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    blocked_targets = [
        target
        for target in result.navigation_targets
        if target.materialization_status == "blocked" and target.rejection_reason == "route_budget_exhausted"
    ]

    assert blocked_targets
    assert blocked_targets[0].parent_target_key == "page:/users"


@pytest.mark.anyio
async def test_page_discovery_merges_duplicate_page_sources():
    result = await PageDiscoveryExtractor().extract(
        browser_session=FakeDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    users_page = next(page for page in result.pages if page.route_path == "/users")
    assert set(users_page.discovery_sources) >= {"runtime_route_hints", "dom_menu_tree", "network_route_config"}


@pytest.mark.anyio
async def test_page_discovery_registry_is_single_source_of_truth_for_duplicate_targets():
    result = await PageDiscoveryExtractor().extract(
        browser_session=DuplicateInteractionDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    tab_targets = [
        target
        for target in result.navigation_targets
        if target.target_kind == "tab_switch" and target.parent_target_key == "page:/users"
    ]
    assert len(tab_targets) == 1
    users_page = next(page for page in result.pages if page.route_path == "/users")
    assert [entry["entry_type"] for entry in users_page.entry_candidates].count("tab_switch") == 1


@pytest.mark.anyio
async def test_page_discovery_keeps_failure_reason_empty_when_optional_network_signal_degrades():
    result = await PageDiscoveryExtractor().extract(
        browser_session=NetworkFailureDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    assert {page.route_path for page in result.pages} >= {"/dashboard", "/users", "/reports"}
    assert result.degraded is False
    assert result.failure_reason is None
    assert any("network route config signals degraded" in message for message in result.warning_messages)


@pytest.mark.anyio
async def test_page_discovery_consumes_network_resource_and_request_collectors():
    browser_session = NetworkSignalDiscoverySession()
    result = await PageDiscoveryExtractor().extract(
        browser_session=browser_session,
        system=None,
        crawl_scope="full",
    )

    assert {page.route_path for page in result.pages} >= {"/dashboard", "/reports", "/users"}
    assert browser_session.network_resource_hints_calls == 1
    assert browser_session.network_requests_calls == 1


@pytest.mark.anyio
async def test_page_discovery_metadata_failure_only_adds_warning_when_pages_are_usable():
    result = await PageDiscoveryExtractor().extract(
        browser_session=MetadataFailureDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    assert {page.route_path for page in result.pages} >= {"/dashboard", "/users", "/reports"}
    assert result.degraded is False
    assert result.failure_reason is None
    assert any("page metadata validation degraded" in message for message in result.warning_messages)


@pytest.mark.anyio
async def test_page_discovery_network_subsignals_degrade_independently():
    browser_session = PartialNetworkFailureDiscoverySession()
    result = await PageDiscoveryExtractor().extract(
        browser_session=browser_session,
        system=None,
        crawl_scope="full",
    )

    assert {page.route_path for page in result.pages} >= {"/dashboard", "/users", "/reports", "/alerts"}
    assert browser_session.network_route_config_calls == 1
    assert browser_session.network_resource_hints_calls == 1
    assert browser_session.network_requests_calls == 1
    assert result.failure_reason is None
    assert any("network route config signals degraded" in message for message in result.warning_messages)


@pytest.mark.anyio
async def test_page_discovery_metadata_enriches_existing_pages_without_creating_new_pages():
    result = await PageDiscoveryExtractor().extract(
        browser_session=MetadataEnrichmentDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    assert {page.route_path for page in result.pages} == {"/users"}
    users_page = result.pages[0]
    assert users_page.context_constraints == {"reachable": True, "status_code": 200}
