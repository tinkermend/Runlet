from __future__ import annotations

from app.domains.asset_compiler.schemas import StandardCheckDefinition


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

    if has_create_action or _summary_suggests_create_action(page_summary):
        checks.append(
            StandardCheckDefinition(
                check_code="open_create_modal",
                goal="open_create_modal",
                assertion_schema={"assertion": "modal_visible"},
                state_signature=default_state_signature,
            )
        )

    checks.extend(
        _build_representative_state_checks(
            representative_states=representative_states,
            default_state_signature=default_state_signature,
        )
    )

    deduped_checks: list[StandardCheckDefinition] = []
    seen_check_keys: set[tuple[str, str]] = set()
    for check in checks:
        dedupe_key = (check.check_code, _clean_text(check.state_signature))
        if dedupe_key in seen_check_keys:
            continue
        seen_check_keys.add(dedupe_key)
        deduped_checks.append(check)

    return deduped_checks


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
                    check_code="open_create_modal",
                    goal="open_create_modal",
                    assertion_schema={"assertion": "modal_visible"},
                    state_signature=state_signature,
                )
            )

    return checks


def _summary_suggests_create_action(page_summary: str | None) -> bool:
    if not page_summary:
        return False
    normalized = page_summary.strip()
    return any(keyword in normalized for keyword in ("新增", "创建", "新建"))


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
