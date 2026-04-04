from app.domains.asset_compiler.template_registry import list_templates


def test_template_registry_contains_v1_readonly_templates():
    template_codes = {item.template_code for item in list_templates(version="v1")}
    assert template_codes == {
        "has_data",
        "no_data",
        "field_equals_exists",
        "status_exists",
        "count_gte",
    }
