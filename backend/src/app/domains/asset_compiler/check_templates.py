from __future__ import annotations

from app.domains.asset_compiler.schemas import StandardCheckDefinition
from app.domains.asset_compiler.template_registry import list_templates


def build_standard_checks(
    *,
    page_summary: str | None,
    has_table: bool,
    has_create_action: bool = False,
    representative_states: list[dict[str, object]] | None = None,
    default_state_signature: str | None = None,
) -> list[StandardCheckDefinition]:
    checks = [
        StandardCheckDefinition(
            check_code="page_open",
            goal="page_open",
            assertion_schema={"assertion": "page_ready"},
            state_signature=default_state_signature,
        )
    ]

    if has_table:
        checks.append(
            StandardCheckDefinition(
                check_code="table_render",
                goal="table_render",
                assertion_schema={"assertion": "table_visible"},
                state_signature=default_state_signature,
            )
        )
        checks.extend(
            _build_template_checks(
                default_state_signature=default_state_signature,
            )
        )

    if has_create_action or _summary_suggests_create_action(page_summary):
        checks.append(
            StandardCheckDefinition(
                check_code="open_create_modal",
                goal="open_create_modal",
                assertion_schema={
                    "assertion": "page_ready",
                    "required_elements": [{"kind": "button", "role": "button"}],
                },
                state_signature=default_state_signature,
            )
        )

    checks.extend(
        _build_representative_state_checks(
            representative_states=representative_states,
            default_state_signature=default_state_signature,
        )
    )

    selected_by_code: dict[str, StandardCheckDefinition] = {}
    for check in checks:
        existing = selected_by_code.get(check.check_code)
        if existing is None:
            selected_by_code[check.check_code] = check
            continue
        if _prefer_new_check(
            existing=existing,
            candidate=check,
            default_state_signature=default_state_signature,
        ):
            selected_by_code[check.check_code] = check

    return list(selected_by_code.values())


def _build_representative_state_checks(
    *,
    representative_states: list[dict[str, object]] | None,
    default_state_signature: str | None,
) -> list[StandardCheckDefinition]:
    checks: list[StandardCheckDefinition] = []
    for state in representative_states or []:
        state_signature = _clean_text(state.get("state_signature"))
        if not state_signature or state_signature == _clean_text(default_state_signature):
            continue
        entry_type = _clean_text(state.get("entry_type"))
        if entry_type == "tab_switch":
            checks.append(
                StandardCheckDefinition(
                    check_code="tab_switch_render",
                    goal="tab_switch_render",
                    assertion_schema={"assertion": "table_visible"},
                    state_signature=state_signature,
                )
            )
        elif entry_type == "open_modal":
            checks.append(
                StandardCheckDefinition(
                    check_code="open_create_modal_state",
                    goal="open_create_modal",
                    assertion_schema={"assertion": "modal_visible"},
                    state_signature=state_signature,
                )
            )

    return checks


def _build_template_checks(
    *,
    default_state_signature: str | None,
) -> list[StandardCheckDefinition]:
    template_checks: list[StandardCheckDefinition] = []
    for template in list_templates(version="v1"):
        template_checks.append(
            StandardCheckDefinition(
                check_code=template.template_code,
                goal=template.template_code,
                input_schema={"required_slots": list(template.required_slots)},
                assertion_schema=dict(template.assertion_contract),
                state_signature=default_state_signature,
            )
        )
    return template_checks


def _summary_suggests_create_action(page_summary: str | None) -> bool:
    if not page_summary:
        return False
    normalized = page_summary.strip()
    return any(keyword in normalized for keyword in ("新增", "创建", "新建"))


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _prefer_new_check(
    *,
    existing: StandardCheckDefinition,
    candidate: StandardCheckDefinition,
    default_state_signature: str | None,
) -> bool:
    default_signature = _clean_text(default_state_signature)
    existing_signature = _clean_text(existing.state_signature)
    candidate_signature = _clean_text(candidate.state_signature)
    existing_is_default = existing_signature == default_signature
    candidate_is_default = candidate_signature == default_signature

    if existing_is_default and not candidate_is_default:
        return True
    return False
