from uuid import uuid4

from app.domains.asset_compiler.reconciliation import (
    ACTIVE_PAGE_COUNT_COLLAPSE_RATIO,
    QUALITY_GATE_MIN_SCORE,
    RetirementDecision,
    build_blocking_dependency_json,
    evaluate_retirement_quality_gate,
)


def test_retirement_decision_exposes_asset_and_check_identifiers():
    decision = RetirementDecision(
        page_asset_id=uuid4(),
        page_check_ids=[uuid4()],
        reason="missing_page",
    )

    assert decision.reason == "missing_page"
    assert len(decision.page_check_ids) == 1


def test_build_blocking_dependency_json_derives_menu_chain_and_required_elements():
    dependencies = build_blocking_dependency_json(
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {
                "module": "nav.menu_chain",
                "params": {"menu_chain": ["系统管理", "用户管理"], "route_path": "/users"},
            },
            {"module": "assert.table_visible", "params": {}},
        ],
        assertion_schema={"required_elements": [{"kind": "button", "text": "新增用户"}]},
    )

    assert dependencies == {
        "menu_chain": ["系统管理", "用户管理"],
        "required_elements": [
            {"kind": "button", "text": "新增用户"},
            {"kind": "table", "role": "table"},
        ],
    }


def test_evaluate_retirement_quality_gate_blocks_page_count_collapse():
    decision = evaluate_retirement_quality_gate(
        crawl_type="full",
        degraded=False,
        quality_score=QUALITY_GATE_MIN_SCORE,
        current_page_count=1,
        previous_active_page_count=10,
    )

    assert decision.allow_retirement is False
    assert decision.warning_payload is not None
    assert decision.warning_payload["reason"] == "page_count_collapse"
    assert decision.warning_payload["collapse_ratio"] < ACTIVE_PAGE_COUNT_COLLAPSE_RATIO


def test_evaluate_retirement_quality_gate_passes_for_high_quality_full_snapshot():
    decision = evaluate_retirement_quality_gate(
        crawl_type="full",
        degraded=False,
        quality_score=QUALITY_GATE_MIN_SCORE,
        current_page_count=9,
        previous_active_page_count=10,
    )

    assert decision.allow_retirement is True
    assert decision.warning_payload is None
