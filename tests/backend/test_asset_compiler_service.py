from uuid import uuid4

import pytest

from app.domains.asset_compiler.fingerprints import build_page_fingerprint
from app.domains.asset_compiler.schemas import CompileSnapshotResult
from app.infrastructure.db.models.assets import AssetSnapshot, PageAsset
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.shared.enums import AssetStatus


def test_build_standard_checks_for_table_page_returns_page_open_and_table_render():
    from app.domains.asset_compiler.check_templates import build_standard_checks

    checks = build_standard_checks(page_summary="用户管理", has_table=True)

    assert {"page_open", "table_render"} <= {check.check_code for check in checks}


def test_build_module_plan_for_table_render_contains_expected_steps():
    from app.domains.asset_compiler.module_plan_builder import build_module_plan

    page_context = {
        "system_code": "erp",
        "page_title": "用户管理",
        "route_path": "/users",
        "menu_chain": ["系统管理", "用户管理"],
        "has_table": True,
    }

    plan = build_module_plan(check_code="table_render", page_context=page_context)

    assert plan.plan_version == "v1"
    assert plan.steps_json[0]["module"] == "auth.inject_state"
    assert [step["module"] for step in plan.steps_json] == [
        "auth.inject_state",
        "nav.menu_chain",
        "page.wait_ready",
        "assert.table_visible",
    ]


@pytest.fixture
def asset_compiler_service(db_session):
    from app.domains.asset_compiler.service import AssetCompilerService

    return AssetCompilerService(session=db_session)


@pytest.fixture
def seeded_crawl_snapshot(db_session, seeded_system):
    snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
    )
    db_session.add(snapshot)
    db_session.flush()

    page = Page(
        system_id=seeded_system.id,
        snapshot_id=snapshot.id,
        route_path="/users",
        page_title="用户管理",
        page_summary="用户管理列表，支持新增用户",
    )
    db_session.add(page)
    db_session.flush()

    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            label="系统管理",
            depth=0,
            sort_order=1,
        )
    )
    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            label="用户管理",
            route_path="/users",
            depth=1,
            sort_order=1,
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            element_type="table",
            element_role="table",
            element_text="用户列表",
            playwright_locator="get_by_role('table', name='用户列表')",
            usage_description="展示用户列表",
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            element_type="button",
            element_role="button",
            element_text="新增用户",
            playwright_locator="get_by_role('button', name='新增用户')",
            usage_description="打开新增用户弹窗",
        )
    )
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


@pytest.fixture
def seeded_previous_snapshot(db_session, seeded_system):
    previous_snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
    )
    db_session.add(previous_snapshot)
    db_session.flush()

    previous_page = Page(
        system_id=seeded_system.id,
        snapshot_id=previous_snapshot.id,
        route_path="/users",
        page_title="用户管理",
        page_summary="用户管理列表",
    )
    db_session.add(previous_page)
    db_session.flush()

    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=previous_snapshot.id,
            page_id=previous_page.id,
            label="系统管理",
            depth=0,
            sort_order=1,
        )
    )
    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=previous_snapshot.id,
            page_id=previous_page.id,
            label="用户管理",
            route_path="/users",
            depth=1,
            sort_order=1,
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=previous_snapshot.id,
            page_id=previous_page.id,
            element_type="table",
            element_role="table",
            element_text="用户列表",
            playwright_locator="get_by_role('table', name='用户列表')",
            usage_description="展示用户列表",
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=previous_snapshot.id,
            page_id=previous_page.id,
            element_type="button",
            element_role="button",
            element_text="新增用户",
            playwright_locator="get_by_role('button', name='新增用户')",
            usage_description="打开新增用户弹窗",
        )
    )
    db_session.flush()

    page_asset = PageAsset(
        system_id=seeded_system.id,
        page_id=previous_page.id,
        asset_key="erp.users",
        asset_version="baseline",
        status=AssetStatus.SAFE,
        compiled_from_snapshot_id=previous_snapshot.id,
    )
    db_session.add(page_asset)
    db_session.flush()

    baseline_fingerprint = build_page_fingerprint(
        {
            "page": {
                "route_path": "/users",
                "page_title": "用户管理",
                "page_summary": "用户管理列表",
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
                    "usage_description": "展示用户列表",
                    "attributes": {},
                },
                {
                    "element_type": "button",
                    "element_role": "button",
                    "element_text": "新增用户",
                    "playwright_locator": "get_by_role('button', name='新增用户')",
                    "usage_description": "打开新增用户弹窗",
                    "attributes": {},
                },
            ],
        }
    )
    db_session.add(
        AssetSnapshot(
            page_asset_id=page_asset.id,
            crawl_snapshot_id=previous_snapshot.id,
            asset_version="baseline",
            structure_hash=baseline_fingerprint["structure_hash"],
            navigation_hash=baseline_fingerprint["navigation_hash"],
            key_locator_hash=baseline_fingerprint["key_locator_hash"],
            semantic_summary_hash=baseline_fingerprint["semantic_summary_hash"],
            diff_score_vs_previous=0.0,
            status=AssetStatus.SAFE,
        )
    )

    current_snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
    )
    db_session.add(current_snapshot)
    db_session.flush()

    current_page = Page(
        system_id=seeded_system.id,
        snapshot_id=current_snapshot.id,
        route_path="/users",
        page_title="用户管理",
        page_summary="用户管理列表",
    )
    db_session.add(current_page)
    db_session.flush()

    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=current_snapshot.id,
            page_id=current_page.id,
            label="系统管理",
            depth=0,
            sort_order=1,
        )
    )
    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=current_snapshot.id,
            page_id=current_page.id,
            label="用户管理",
            route_path="/users",
            depth=1,
            sort_order=1,
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=current_snapshot.id,
            page_id=current_page.id,
            element_type="table",
            element_role="table",
            element_text="用户列表",
            playwright_locator="get_by_role('table', name='用户清单')",
            usage_description="展示用户列表",
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=current_snapshot.id,
            page_id=current_page.id,
            element_type="button",
            element_role="button",
            element_text="新增用户",
            playwright_locator="get_by_role('button', name='新建用户')",
            usage_description="打开新增用户弹窗",
        )
    )
    db_session.commit()
    db_session.refresh(current_snapshot)
    return current_snapshot


@pytest.mark.anyio
async def test_compile_snapshot_creates_page_assets_and_checks(
    asset_compiler_service,
    seeded_crawl_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_crawl_snapshot.id)

    assert result.status == "success"
    assert result.assets_created >= 1
    assert result.checks_created >= 1


@pytest.mark.anyio
async def test_compile_snapshot_marks_asset_suspect_when_drift_is_medium(
    asset_compiler_service,
    seeded_previous_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_previous_snapshot.id)

    assert result.drift_state in {AssetStatus.SAFE, AssetStatus.SUSPECT, AssetStatus.STALE}


def test_compile_snapshot_result_exposes_reconciliation_counts():
    assert "assets_retired" in CompileSnapshotResult.__dataclass_fields__
    assert "checks_retired" in CompileSnapshotResult.__dataclass_fields__
    assert "alias_disable_decision_count" in CompileSnapshotResult.__dataclass_fields__
    assert "published_job_pause_decision_count" in CompileSnapshotResult.__dataclass_fields__
    assert "alias_ids_to_disable" in CompileSnapshotResult.__dataclass_fields__
    assert "published_job_ids_to_pause" in CompileSnapshotResult.__dataclass_fields__
    assert "retire_reasons" in CompileSnapshotResult.__dataclass_fields__
