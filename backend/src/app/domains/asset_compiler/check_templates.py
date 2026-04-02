from __future__ import annotations

from app.domains.asset_compiler.schemas import StandardCheckDefinition


def build_standard_checks(
    *,
    page_summary: str | None,
    has_table: bool,
    has_create_action: bool = False,
) -> list[StandardCheckDefinition]:
    checks = [
        StandardCheckDefinition(
            check_code="page_open",
            goal="page_open",
            assertion_schema={"assertion": "page_ready"},
        )
    ]

    if has_table:
        checks.append(
            StandardCheckDefinition(
                check_code="table_render",
                goal="table_render",
                assertion_schema={"assertion": "table_visible"},
            )
        )

    if has_create_action or _summary_suggests_create_action(page_summary):
        checks.append(
            StandardCheckDefinition(
                check_code="open_create_modal",
                goal="open_create_modal",
                assertion_schema={"assertion": "modal_visible"},
            )
        )

    return checks


def _summary_suggests_create_action(page_summary: str | None) -> bool:
    if not page_summary:
        return False
    normalized = page_summary.strip()
    return any(keyword in normalized for keyword in ("新增", "创建", "新建"))
