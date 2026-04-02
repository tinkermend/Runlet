from __future__ import annotations

from app.domains.asset_compiler.schemas import ModulePlanDraft


def build_module_plan(
    *,
    check_code: str,
    page_context: dict[str, object],
) -> ModulePlanDraft:
    menu_chain = list(page_context.get("menu_chain", []))
    route_path = str(page_context.get("route_path", "") or "")

    steps_json = [
        {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
        {"module": "nav.menu_chain", "params": {"menu_chain": menu_chain, "route_path": route_path}},
        {"module": "page.wait_ready", "params": {"route_path": route_path}},
    ]
    steps_json.append(_assertion_step(check_code))

    return ModulePlanDraft(
        check_code=check_code,
        plan_version="v1",
        steps_json=steps_json,
    )


def _assertion_step(check_code: str) -> dict[str, object]:
    if check_code == "table_render":
        return {"module": "assert.table_visible", "params": {}}
    if check_code == "open_create_modal":
        return {"module": "action.open_create_modal", "params": {}}
    return {"module": "assert.page_ready", "params": {}}
