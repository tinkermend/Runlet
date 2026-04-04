from __future__ import annotations

from app.domains.asset_compiler.schemas import TemplateDefinition


_TEMPLATE_DEFINITIONS: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        template_code="has_data",
        template_version="v1",
        supported_carriers=("table", "list"),
        required_slots=(),
        assertion_contract={"assertion": "data_count", "expected_min": 1},
        compile_strategy={
            "action_chain": ("action.submit_query",),
            "assert_module": "assert.data_count",
            "assert_params": {"expected_min": 1},
        },
    ),
    TemplateDefinition(
        template_code="no_data",
        template_version="v1",
        supported_carriers=("table", "list"),
        required_slots=(),
        assertion_contract={"assertion": "data_count", "expected_max": 0},
        compile_strategy={
            "action_chain": ("action.submit_query",),
            "assert_module": "assert.data_count",
            "assert_params": {"expected_max": 0},
        },
    ),
    TemplateDefinition(
        template_code="field_equals_exists",
        template_version="v1",
        supported_carriers=("table", "list"),
        required_slots=("field", "operator", "value"),
        assertion_contract={
            "assertion": "row_exists_by_field",
            "field": "{{field}}",
            "operator": "{{operator}}",
            "value": "{{value}}",
        },
        compile_strategy={
            "action_chain": ("action.apply_filter", "action.submit_query"),
            "action_params": {
                "action.apply_filter": {
                    "field": "{{field}}",
                    "operator": "{{operator}}",
                    "value": "{{value}}",
                }
            },
            "assert_module": "assert.row_exists_by_field",
            "assert_params": {
                "field": "{{field}}",
                "operator": "{{operator}}",
                "value": "{{value}}",
            },
        },
    ),
    TemplateDefinition(
        template_code="status_exists",
        template_version="v1",
        supported_carriers=("table", "list"),
        required_slots=("status",),
        assertion_contract={
            "assertion": "row_exists_by_field",
            "field": "status",
            "operator": "equals",
            "value": "{{status}}",
        },
        compile_strategy={
            "action_chain": ("action.apply_filter", "action.submit_query"),
            "action_params": {
                "action.apply_filter": {
                    "field": "status",
                    "operator": "equals",
                    "value": "{{status}}",
                }
            },
            "assert_module": "assert.row_exists_by_field",
            "assert_params": {"field": "status", "operator": "equals", "value": "{{status}}"},
        },
    ),
    TemplateDefinition(
        template_code="count_gte",
        template_version="v1",
        supported_carriers=("table", "list"),
        required_slots=("min_count",),
        assertion_contract={"assertion": "data_count", "expected_min": "{{min_count}}"},
        compile_strategy={
            "action_chain": ("action.submit_query",),
            "assert_module": "assert.data_count",
            "assert_params": {"expected_min": "{{min_count}}"},
        },
    ),
)


def list_templates(*, version: str = "v1") -> list[TemplateDefinition]:
    normalized_version = _normalize_text(version) or "v1"
    return [
        template
        for template in _TEMPLATE_DEFINITIONS
        if template.template_version == normalized_version
    ]


def get_template(
    *,
    template_code: str,
    version: str = "v1",
) -> TemplateDefinition | None:
    normalized_code = _normalize_text(template_code)
    normalized_version = _normalize_text(version) or "v1"
    for template in _TEMPLATE_DEFINITIONS:
        if (
            template.template_code == normalized_code
            and template.template_version == normalized_version
        ):
            return template
    return None


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()
