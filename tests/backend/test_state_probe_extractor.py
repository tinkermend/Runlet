import pytest

from app.domains.crawler_service.extractors.state_probe import ControlledStateProbeExtractor


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


@pytest.mark.anyio
async def test_state_probe_dedups_elements_by_state_signature():
    result = await ControlledStateProbeExtractor().extract(
        browser_session=FakeStateProbeSession(),
        system=None,
        crawl_scope="full",
    )

    signatures = [element.state_signature for element in result.elements]
    assert signatures.count("users:modal=create") == 1
    assert "state_signature_duplicate" in result.warning_messages
