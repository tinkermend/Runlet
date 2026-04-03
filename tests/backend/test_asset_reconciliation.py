from uuid import uuid4

from app.domains.asset_compiler.reconciliation import (
    ACTIVE_PAGE_COUNT_COLLAPSE_RATIO,
    QUALITY_GATE_MIN_SCORE,
    ActiveCheckTruth,
    ActivePageTruth,
    SnapshotTruth,
    build_blocking_dependency_json,
    build_current_snapshot_truth,
    evaluate_retirement_quality_gate,
    reconcile_retirement_decisions,
)
from app.infrastructure.db.models.crawl import MenuNode, Page, PageElement


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


def test_build_current_snapshot_truth_ignores_orphan_menus_without_page_id():
    system_id = uuid4()
    snapshot_id = uuid4()
    page_id = uuid4()
    page = Page(
        id=page_id,
        system_id=system_id,
        snapshot_id=snapshot_id,
        route_path="/users",
        page_title="用户管理",
        page_summary="用户管理列表",
    )

    snapshot_truth = build_current_snapshot_truth(
        pages=[page],
        menus=[
            MenuNode(
                system_id=system_id,
                snapshot_id=snapshot_id,
                page_id=None,
                label="巡检管理巡检模板巡检任务巡检结果巡检项",
                depth=0,
                sort_order=0,
            ),
            MenuNode(
                system_id=system_id,
                snapshot_id=snapshot_id,
                page_id=page_id,
                label="系统管理",
                depth=0,
                sort_order=1,
            ),
            MenuNode(
                system_id=system_id,
                snapshot_id=snapshot_id,
                page_id=page_id,
                label="用户管理",
                route_path="/users",
                depth=1,
                sort_order=1,
            ),
        ],
        elements=[
            PageElement(
                system_id=system_id,
                snapshot_id=snapshot_id,
                page_id=page_id,
                element_type="button",
                element_role="button",
                element_text="新增用户",
            )
        ],
    )

    assert snapshot_truth.route_paths == {"/users"}
    assert snapshot_truth.menu_chain_by_route == {"/users": ["系统管理", "用户管理"]}
    assert snapshot_truth.elements_by_route == {
        "/users": [{"kind": "button", "role": "button", "text": "新增用户"}]
    }


def test_reconcile_retirement_decisions_retires_missing_page_when_quality_gate_allows():
    keep_asset_id = uuid4()
    missing_asset_id = uuid4()
    keep_check_id = uuid4()
    missing_check_id = uuid4()
    quality_gate = evaluate_retirement_quality_gate(
        crawl_type="full",
        degraded=False,
        quality_score=0.95,
        current_page_count=1,
        previous_active_page_count=2,
    )

    decisions = reconcile_retirement_decisions(
        active_pages=[
            ActivePageTruth(page_asset_id=keep_asset_id, route_path="/users"),
            ActivePageTruth(page_asset_id=missing_asset_id, route_path="/roles"),
        ],
        active_checks=[
            ActiveCheckTruth(
                page_check_id=keep_check_id,
                page_asset_id=keep_asset_id,
                blocking_dependency_json={"menu_chain": [], "required_elements": []},
            ),
            ActiveCheckTruth(
                page_check_id=missing_check_id,
                page_asset_id=missing_asset_id,
                blocking_dependency_json={"menu_chain": [], "required_elements": []},
            ),
        ],
        snapshot_truth=SnapshotTruth(
            route_paths={"/users"},
            menu_chain_by_route={"/users": ["系统管理", "用户管理"]},
            elements_by_route={"/users": []},
        ),
        quality_gate=quality_gate,
    )

    assert len(decisions) == 1
    assert decisions[0].reason == "missing_page"
    assert decisions[0].page_asset_id == missing_asset_id
    assert decisions[0].page_check_ids == [missing_check_id]


def test_reconcile_retirement_decisions_skips_retirement_when_quality_gate_rejects():
    decision = evaluate_retirement_quality_gate(
        crawl_type="full",
        degraded=False,
        quality_score=QUALITY_GATE_MIN_SCORE,
        current_page_count=1,
        previous_active_page_count=10,
    )

    decisions = reconcile_retirement_decisions(
        active_pages=[ActivePageTruth(page_asset_id=uuid4(), route_path="/users")],
        active_checks=[],
        snapshot_truth=SnapshotTruth(route_paths=set(), menu_chain_by_route={}, elements_by_route={}),
        quality_gate=decision,
    )

    assert decision.allow_retirement is False
    assert decision.warning_payload is not None
    assert decision.warning_payload["reason"] == "page_count_collapse"
    assert decision.warning_payload["collapse_ratio"] < ACTIVE_PAGE_COUNT_COLLAPSE_RATIO
    assert decisions == []


def test_reconcile_retirement_decisions_retires_check_when_menu_chain_missing():
    page_asset_id = uuid4()
    check_id = uuid4()
    quality_gate = evaluate_retirement_quality_gate(
        crawl_type="full",
        degraded=False,
        quality_score=0.95,
        current_page_count=1,
        previous_active_page_count=1,
    )

    decisions = reconcile_retirement_decisions(
        active_pages=[ActivePageTruth(page_asset_id=page_asset_id, route_path="/users")],
        active_checks=[
            ActiveCheckTruth(
                page_check_id=check_id,
                page_asset_id=page_asset_id,
                blocking_dependency_json={
                    "menu_chain": ["系统管理", "用户管理"],
                    "required_elements": [],
                },
            )
        ],
        snapshot_truth=SnapshotTruth(
            route_paths={"/users"},
            menu_chain_by_route={"/users": ["用户管理"]},
            elements_by_route={"/users": []},
        ),
        quality_gate=quality_gate,
    )

    assert len(decisions) == 1
    assert decisions[0].reason == "missing_menu_chain"
    assert decisions[0].page_check_ids == [check_id]


def test_reconcile_retirement_decisions_retires_check_when_key_element_missing():
    page_asset_id = uuid4()
    check_id = uuid4()
    quality_gate = evaluate_retirement_quality_gate(
        crawl_type="full",
        degraded=False,
        quality_score=0.95,
        current_page_count=1,
        previous_active_page_count=1,
    )

    decisions = reconcile_retirement_decisions(
        active_pages=[ActivePageTruth(page_asset_id=page_asset_id, route_path="/users")],
        active_checks=[
            ActiveCheckTruth(
                page_check_id=check_id,
                page_asset_id=page_asset_id,
                blocking_dependency_json={
                    "menu_chain": ["系统管理", "用户管理"],
                    "required_elements": [{"kind": "button", "text": "新增用户"}],
                },
            )
        ],
        snapshot_truth=SnapshotTruth(
            route_paths={"/users"},
            menu_chain_by_route={"/users": ["系统管理", "用户管理"]},
            elements_by_route={"/users": [{"kind": "table", "role": "table", "text": "用户列表"}]},
        ),
        quality_gate=quality_gate,
    )

    assert len(decisions) == 1
    assert decisions[0].reason == "missing_key_element"
    assert decisions[0].page_check_ids == [check_id]
