from app.domains.asset_compiler.locator_bundles import build_locator_bundle


def test_compile_locator_bundle_prefers_semantic_then_label_then_testid():
    bundle = build_locator_bundle(
        locator_candidates=[
            {"strategy_type": "css", "selector": ".btn.btn-primary"},
            {"strategy_type": "testid", "selector": "[data-testid='create-user']"},
            {"strategy_type": "semantic", "selector": "role=button[name='新增用户']"},
            {"strategy_type": "label", "selector": "label=新增用户"},
        ],
        state_context={"modal_title": "新增用户"},
    )

    assert [item["strategy_type"] for item in bundle.candidates[:4]] == [
        "semantic",
        "label",
        "testid",
        "css",
    ]


def test_compile_locator_bundle_filters_forbidden_locator_strategies():
    bundle = build_locator_bundle(
        locator_candidates=[
            {"strategy_type": "css", "selector": "#user-row-173894"},
            {"strategy_type": "css", "selector": "ul>li:nth-child(3)"},
            {
                "strategy_type": "css",
                "selector": ".page .table .row .cell .button .inner .text",
            },
            {"strategy_type": "css", "selector": ".btn.__a12bc9f"},
            {"strategy_type": "semantic", "selector": "role=button[name='新增用户']"},
        ],
        state_context={"active_tab": "enabled"},
    )

    assert [item["selector"] for item in bundle.candidates] == ["role=button[name='新增用户']"]
