from app.infrastructure.db.models.assets import AssetSnapshot, ModulePlan, PageAsset, PageCheck
from app.shared.enums import AssetStatus


def _page_payload() -> dict[str, object]:
    return {
        "page": {
            "route_path": "/users",
            "page_title": "用户管理",
            "page_summary": "用户管理列表页面",
        },
        "menus": [
            {"label": "系统管理", "route_path": None, "depth": 0, "sort_order": 1},
            {"label": "用户管理", "route_path": "/users", "depth": 1, "sort_order": 1},
        ],
        "elements": [
            {
                "element_type": "table",
                "element_role": "table",
                "element_text": "用户列表",
                "playwright_locator": "get_by_role('table', name='用户列表')",
                "attributes": {"data-testid": "users-table"},
                "usage_description": "展示用户列表",
            },
            {
                "element_type": "button",
                "element_role": "button",
                "element_text": "新增用户",
                "playwright_locator": "get_by_role('button', name='新增用户')",
                "attributes": {"data-testid": "create-user"},
                "usage_description": "打开新增用户弹窗",
            },
        ],
    }


def test_page_asset_exposes_drift_tracking_fields():
    assert hasattr(PageAsset, "compiled_from_snapshot_id")
    assert hasattr(PageAsset, "status")
    assert hasattr(PageCheck, "success_rate")
    assert hasattr(ModulePlan, "plan_version")
    assert hasattr(AssetSnapshot, "navigation_hash")
    assert hasattr(AssetSnapshot, "key_locator_hash")
    assert hasattr(AssetSnapshot, "semantic_summary_hash")
    assert hasattr(AssetSnapshot, "diff_score_vs_previous")
    assert AssetStatus.SAFE.value == "safe"
    assert AssetStatus.SUSPECT.value == "suspect"
    assert AssetStatus.STALE.value == "stale"


def test_build_structure_fingerprint_is_stable_for_same_page_shape():
    from app.domains.asset_compiler.fingerprints import build_page_fingerprint

    page_payload = _page_payload()

    fingerprint_a = build_page_fingerprint(page_payload)
    fingerprint_b = build_page_fingerprint(page_payload)

    assert fingerprint_a == fingerprint_b


def test_diff_score_increases_when_key_locators_change():
    from app.domains.asset_compiler.fingerprints import compare_fingerprints

    old_fp = {
        "navigation_hash": "nav-1",
        "key_locator_hash": "locator-1",
        "semantic_summary_hash": "summary-1",
        "structure_hash": "structure-1",
    }
    new_fp = {
        "navigation_hash": "nav-1",
        "key_locator_hash": "locator-2",
        "semantic_summary_hash": "summary-1",
        "structure_hash": "structure-2",
    }

    diff = compare_fingerprints(old_fp, new_fp)

    assert diff.score > 0
    assert diff.changed_components == {"key_locator_hash", "structure_hash"}
    assert diff.status in {AssetStatus.SAFE, AssetStatus.SUSPECT, AssetStatus.STALE}
