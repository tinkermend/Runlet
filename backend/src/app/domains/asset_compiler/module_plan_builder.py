from __future__ import annotations

from app.domains.asset_compiler.schemas import ModulePlanDraft


def build_module_plan(
    *,
    check_code: str,
    page_context: dict[str, object],
    state_signature: str | None = None,
    locator_bundle: dict[str, object] | None = None,
) -> ModulePlanDraft:
    menu_chain = list(page_context.get("menu_chain", []))
    route_path = str(page_context.get("route_path", "") or "")
    default_state_signature = str(page_context.get("default_state_signature", "") or "")

    steps_json = [
        {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
        {"module": "nav.menu_chain", "params": {"menu_chain": menu_chain, "route_path": route_path}},
        {"module": "page.wait_ready", "params": {"route_path": route_path}},
    ]
    normalized_state_signature = str(state_signature or "")
    if normalized_state_signature and normalized_state_signature != default_state_signature:
        steps_json.append(
            {"module": "state.enter", "params": {"state_signature": normalized_state_signature}}
        )

    steps_json.append(
        {
            "module": "locator.assert",
            "params": {
                "assertion": _assertion_name(check_code),
                "expected_element_type": _expected_element_type(check_code),
                "locator_bundle": locator_bundle or {"candidates": []},
            },
        }
    )

    return ModulePlanDraft(
        check_code=check_code,
        plan_version="v1",
        steps_json=steps_json,
    )


def _assertion_name(check_code: str) -> str:
    if check_code == "table_render":
        return "table_visible"
    if check_code == "tab_switch_render":
        return "table_visible"
    if check_code == "open_create_modal":
        return "modal_visible"
    return "page_ready"


def _expected_element_type(check_code: str) -> str:
    if check_code in {"table_render", "tab_switch_render"}:
        return "table"
    if check_code == "open_create_modal":
        return "dialog"
    return "page"
