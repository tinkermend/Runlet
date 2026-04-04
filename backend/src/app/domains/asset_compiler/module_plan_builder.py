from __future__ import annotations

from app.domains.asset_compiler.schemas import ModulePlanDraft
from app.domains.asset_compiler.template_registry import get_template


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

    template = get_template(template_code=check_code, version="v1")
    if template is not None:
        steps_json.extend(
            _build_template_chain_steps(
                check_code=check_code,
                page_context=page_context,
            )
        )
        return ModulePlanDraft(
            check_code=check_code,
            plan_version="v1",
            steps_json=steps_json,
        )

    if _uses_legacy_open_create_action(
        check_code=check_code,
        state_signature=normalized_state_signature,
        default_state_signature=default_state_signature,
    ):
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
        steps_json.append({"module": "action.open_create_modal", "params": {}})
        return ModulePlanDraft(
            check_code=check_code,
            plan_version="v1",
            steps_json=steps_json,
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
        return "page_ready"
    if check_code == "open_create_modal_state":
        return "modal_visible"
    return "page_ready"


def _expected_element_type(check_code: str) -> str:
    if check_code in {"table_render", "tab_switch_render"}:
        return "table"
    if check_code == "open_create_modal":
        return "button"
    if check_code == "open_create_modal_state":
        return "dialog"
    return "page"


def _uses_legacy_open_create_action(
    *,
    check_code: str,
    state_signature: str,
    default_state_signature: str,
) -> bool:
    if check_code != "open_create_modal":
        return False
    if not state_signature:
        return True
    return state_signature == default_state_signature


def _build_template_chain_steps(
    *,
    check_code: str,
    page_context: dict[str, object],
) -> list[dict[str, object]]:
    template = get_template(template_code=check_code, version="v1")
    if template is None:
        return []

    carrier = _resolve_carrier_hint(page_context=page_context)
    compile_strategy = template.compile_strategy
    action_chain = compile_strategy.get("action_chain", ())
    action_params_map = compile_strategy.get("action_params", {})
    if not isinstance(action_params_map, dict):
        action_params_map = {}

    steps: list[dict[str, object]] = []
    for module in action_chain:
        params: dict[str, object] = {"carrier": carrier}
        module_params = action_params_map.get(module)
        if isinstance(module_params, dict):
            params.update(module_params)
        steps.append({"module": module, "params": params})

    assert_module = str(compile_strategy.get("assert_module", "") or "")
    if not assert_module:
        return steps

    assert_params: dict[str, object] = {"carrier": carrier}
    raw_assert_params = compile_strategy.get("assert_params", {})
    if isinstance(raw_assert_params, dict):
        assert_params.update(raw_assert_params)
    steps.append({"module": assert_module, "params": assert_params})
    return steps


def _resolve_carrier_hint(*, page_context: dict[str, object]) -> str:
    carrier_hint = str(page_context.get("carrier_hint", "") or "").strip().lower()
    if carrier_hint in {"table", "list"}:
        return carrier_hint
    if bool(page_context.get("has_table")):
        return "table"
    return "list"
