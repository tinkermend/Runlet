import pytest

from app.domains.crawler_service.extractors.state_probe import (
    ControlledStateProbeExtractor,
    build_state_signature,
)


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
