import pytest

from app.domains.crawler_service.extractors.page_discovery import build_page_visit_targets
from app.domains.crawler_service.extractors.state_probe import (
    ControlledStateProbeExtractor,
    build_state_signature,
)
from app.domains.crawler_service.schemas import NavigationTargetResult, PageCandidate


class FakeStateProbeSession:
    framework_hint = "react"
    performed_actions: list[str] = []

    def __init__(self) -> None:
        type(self).performed_actions = []
        self.actions = [
            {
                "route_path": "/users",
                "entry_type": "tab_switch",
                "state_context": {"active_tab": "default"},
                "elements": [
                    {
                        "element_type": "table",
                        "role": "grid",
                        "text": "用户列表",
                        "locator_candidates": [
                            {
                                "strategy_type": "semantic",
                                "selector": "role=grid[name='用户列表']",
                            }
                        ],
                    }
                ],
            },
            {
                "route_path": "/users",
                "entry_type": "tab_switch",
                "state_context": {"active_tab": "disabled"},
                "elements": [
                    {
                        "element_type": "button",
                        "role": "button",
                        "text": "启用用户",
                        "locator_candidates": [
                            {
                                "strategy_type": "semantic",
                                "selector": "role=button[name='启用用户']",
                            }
                        ],
                    }
                ],
            },
            {
                "route_path": "/users",
                "entry_type": "open_modal",
                "state_context": {"modal_title": "create"},
                "elements": [
                    {
                        "element_type": "input",
                        "role": "textbox",
                        "text": "用户名",
                    }
                ],
            },
            {
                "route_path": "/users",
                "entry_type": "open_modal",
                "state_context": {"modal_title": "create"},
                "elements": [
                    {
                        "element_type": "input",
                        "role": "textbox",
                        "text": "用户名",
                    }
                ],
            },
            {
                "route_path": "/users",
                "entry_type": "submit_form",
                "state_context": {"modal_title": "create"},
                "elements": [],
            },
        ]

    async def collect_state_probe_actions(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return [dict(action) for action in self.actions]

    async def perform_state_probe_action(
        self,
        *,
        action: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        del crawl_scope
        entry_type = str(action.get("entry_type") or "")
        type(self).performed_actions.append(entry_type)
        return {
            "route_path": action.get("route_path"),
            "state_context": action.get("state_context"),
            "elements": action.get("elements"),
        }


class MixedProbeWarningSession(FakeStateProbeSession):
    def __init__(self) -> None:
        super().__init__()
        self.actions = [
            {
                "route_path": "/users",
                "entry_type": "tab_switch",
                "state_context": {"active_tab": "default"},
                "elements": [
                    {
                        "element_type": "table",
                        "role": "grid",
                        "text": "用户列表",
                    }
                ],
            },
            {
                "route_path": "/users",
                "entry_type": "open_modal",
                "blocked_by_permission": True,
                "state_context": {"modal_title": "create"},
                "elements": [],
            },
            {
                "route_path": "/users",
                "entry_type": "submit_form",
                "state_context": {"modal_title": "create"},
                "elements": [],
            },
        ]


class NotAppliedStateProbeSession(FakeStateProbeSession):
    def __init__(self) -> None:
        super().__init__()
        self.actions = [
            {
                "route_path": "/users",
                "entry_type": "tab_switch",
                "state_context": {"active_tab": "disabled"},
                "elements": [
                    {
                        "element_type": "table",
                        "role": "grid",
                        "text": "禁用用户列表(伪)",
                    }
                ],
            },
        ]

    async def collect_state_probe_baseline(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return []

    async def perform_state_probe_action(
        self,
        *,
        action: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        del crawl_scope
        return {
            "route_path": action.get("route_path"),
            "state_context": action.get("state_context"),
            "elements": action.get("elements"),
            "probe_applied": False,
            "probe_apply_reason": "target_panel_not_materialized",
        }


class UnsafeOnlyStateProbeSession(FakeStateProbeSession):
    def __init__(self) -> None:
        super().__init__()
        self.actions = [
            {
                "route_path": "/users",
                "entry_type": "submit_form",
                "state_context": {"modal_title": "create"},
                "elements": [
                    {
                        "element_type": "button",
                        "role": "button",
                        "text": "提交",
                    }
                ],
            },
        ]

    async def collect_state_probe_baseline(self, *, crawl_scope: str) -> list[dict[str, object]]:
        del crawl_scope
        return []


class PageVisitFirstStateProbeSession:
    framework_hint = "react"

    def __init__(self) -> None:
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


class PageVisitFirstNotAppliedSession(PageVisitFirstStateProbeSession):
    async def perform_navigation_target(
        self,
        *,
        target: dict[str, object],
        page_context: dict[str, object],
        crawl_scope: str,
    ) -> dict[str, object]:
        del page_context, crawl_scope
        self.performed_payloads.append(dict(target))
        entry_type = str(target.get("entry_type") or target.get("interaction_type") or "")
        self.performed_targets.append(entry_type)
        return {
            "route_path": "/reports",
            "state_context": {"active_tab": "已归档"},
            "elements": [],
            "probe_applied": False,
            "probe_apply_reason": "target_panel_not_materialized",
        }


@pytest.mark.anyio
async def test_state_probe_collects_representative_states_without_unsafe_actions():
    extractor = ControlledStateProbeExtractor()
    result = await extractor.extract(browser_session=FakeStateProbeSession(), system=None, crawl_scope="full")

    assert {element.state_signature for element in result.elements} >= {
        "users:default",
        "users:tab=disabled",
        "users:modal=create",
    }
    assert "submit_form" not in FakeStateProbeSession.performed_actions


@pytest.mark.anyio
async def test_state_probe_stops_when_interaction_budget_is_exhausted():
    result = await ControlledStateProbeExtractor(max_actions_per_page=2).extract(
        browser_session=FakeStateProbeSession(),
        system=None,
        crawl_scope="full",
    )

    assert "interaction_budget_exhausted" in result.warning_messages
    budget_blocked_targets = [
        target
        for target in result.navigation_targets
        if target.materialization_status == "blocked" and target.rejection_reason == "route_budget_exhausted"
    ]
    assert budget_blocked_targets


@pytest.mark.anyio
async def test_state_probe_dedups_elements_by_state_signature():
    result = await ControlledStateProbeExtractor().extract(
        browser_session=FakeStateProbeSession(),
        system=None,
        crawl_scope="full",
    )

    signatures = [element.state_signature for element in result.elements]
    assert signatures.count("users:modal=create") == 1
    assert "navigation_target_duplicate" in result.warning_messages


def test_build_state_signature_includes_numeric_pagination_context():
    page_1 = build_state_signature("/users", {"active_tab": "default", "page_number": 1})
    page_2 = build_state_signature("/users", {"active_tab": "default", "page_number": 2})

    assert page_1 != page_2
    assert "page_number=1" in page_1
    assert "page_number=2" in page_2


@pytest.mark.anyio
async def test_state_probe_permission_and_unsafe_actions_only_emit_warnings_when_usable():
    result = await ControlledStateProbeExtractor().extract(
        browser_session=MixedProbeWarningSession(),
        system=None,
        crawl_scope="full",
    )

    assert result.failure_reason is None
    assert result.elements
    assert "blocked_by_permission" in result.warning_messages
    assert "unsafe_action_rejected" in result.warning_messages


@pytest.mark.anyio
async def test_state_probe_skips_state_when_action_was_not_applied():
    result = await ControlledStateProbeExtractor().extract(
        browser_session=NotAppliedStateProbeSession(),
        system=None,
        crawl_scope="full",
    )

    assert result.elements == []
    assert result.failure_reason is None
    assert "state_transition_not_applied" in result.warning_messages
    target = result.navigation_targets[0]
    assert target.materialization_status == "not_applied"
    assert target.rejection_reason == "state_transition_not_applied"
    assert target.rejection_detail == "target_panel_not_materialized"


@pytest.mark.anyio
async def test_state_probe_unsupported_action_is_warning_only_and_produces_no_state():
    result = await ControlledStateProbeExtractor().extract(
        browser_session=UnsafeOnlyStateProbeSession(),
        system=None,
        crawl_scope="full",
    )

    assert result.failure_reason is None
    assert result.elements == []
    assert "unsafe_action_rejected" in result.warning_messages


@pytest.mark.anyio
async def test_state_probe_visits_discovered_pages_before_deriving_state_targets():
    browser_session = PageVisitFirstStateProbeSession()
    page_candidates = [
        PageCandidate(route_path="/dashboard", page_title="仪表盘"),
        PageCandidate(route_path="/reports", page_title="报表中心"),
    ]
    page_targets = build_page_visit_targets(
        pages=page_candidates,
        navigation_targets=[
            NavigationTargetResult(
                target_key="page:/dashboard",
                target_kind="page_route",
                route_hint="/dashboard",
                materialization_status="queued",
            ),
            NavigationTargetResult(
                target_key="page:/reports",
                target_kind="page_route",
                route_hint="/reports",
                materialization_status="queued",
            ),
        ],
    )

    result = await ControlledStateProbeExtractor().extract(
        browser_session=browser_session,
        system=None,
        crawl_scope="full",
        page_candidates=page_candidates,
        navigation_targets=[target.to_record() for target in page_targets],
    )

    assert browser_session.visited_routes == ["/dashboard", "/reports"]
    assert browser_session.performed_targets == ["tab_switch"]
    assert browser_session.performed_payloads[0]["entry_type"] == "tab_switch"
    assert browser_session.performed_payloads[0]["interaction_type"] == "tab_switch"
    assert {element.state_signature for element in result.elements} >= {
        "dashboard:default",
        "reports:tab=已归档",
    }


@pytest.mark.anyio
async def test_state_probe_page_first_propagates_failure_detail_and_warning():
    browser_session = PageVisitFirstNotAppliedSession()
    page_candidates = [
        PageCandidate(route_path="/reports", page_title="报表中心"),
    ]

    result = await ControlledStateProbeExtractor().extract(
        browser_session=browser_session,
        system=None,
        crawl_scope="full",
        page_candidates=page_candidates,
        navigation_targets=[
            NavigationTargetResult(
                target_key="tab:/reports/archived",
                target_kind="tab_switch",
                route_hint="/reports",
                parent_target_key="page:/reports",
                state_context={"active_tab": "已归档"},
                materialization_status="queued",
            )
        ],
    )

    assert browser_session.performed_targets == ["tab_switch"]
    assert "state_transition_not_applied" in result.warning_messages
    assert "target_panel_not_materialized" in result.warning_messages
    target = next(target for target in result.navigation_targets if target.target_kind == "tab_switch")
    assert target.materialization_status == "not_applied"
    assert target.rejection_reason == "state_transition_not_applied"
    assert target.rejection_detail == "target_panel_not_materialized"
