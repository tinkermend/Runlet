from uuid import uuid4

import pytest
from sqlmodel import select

from app.domains.asset_compiler.fingerprints import build_page_fingerprint
from app.domains.asset_compiler.schemas import CompileSnapshotResult
from app.infrastructure.db.models.assets import (
    AssetReconciliationAudit,
    AssetSnapshot,
    IntentAlias,
    ModulePlan,
    PageAsset,
    PageCheck,
)
from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.jobs import PublishedJob
from app.shared.enums import AssetLifecycleStatus, AssetStatus, PublishedJobState


def test_build_standard_checks_for_table_page_returns_page_open_and_table_render():
    from app.domains.asset_compiler.check_templates import build_standard_checks

    checks = build_standard_checks(page_summary="用户管理", has_table=True)

    assert {"page_open", "table_render"} <= {check.check_code for check in checks}


def test_build_standard_checks_adds_representative_state_checks():
    from app.domains.asset_compiler.check_templates import build_standard_checks

    checks = build_standard_checks(
        page_summary="用户管理",
        has_table=True,
        representative_states=[
            {"state_signature": "users:tab=disabled", "entry_type": "tab_switch"},
            {"state_signature": "users:modal=create", "entry_type": "open_modal"},
        ],
    )

    assert {"tab_switch_render", "open_create_modal"} <= {check.check_code for check in checks}


def test_build_module_plan_for_table_render_contains_expected_steps():
    from app.domains.asset_compiler.module_plan_builder import build_module_plan

    locator_bundle = {
        "candidates": [
            {"strategy_type": "semantic", "selector": "role=table[name='用户列表']"},
            {"strategy_type": "css", "selector": ".users-table"},
        ]
    }
    page_context = {
        "system_code": "erp",
        "page_title": "用户管理",
        "route_path": "/users",
        "menu_chain": ["系统管理", "用户管理"],
        "has_table": True,
        "default_state_signature": "users:default",
    }

    plan = build_module_plan(
        check_code="table_render",
        page_context=page_context,
        state_signature="users:tab=disabled",
        locator_bundle=locator_bundle,
    )

    assert plan.plan_version == "v1"
    assert plan.steps_json[0]["module"] == "auth.inject_state"
    assert [step["module"] for step in plan.steps_json] == [
        "auth.inject_state",
        "nav.menu_chain",
        "page.wait_ready",
        "state.enter",
        "locator.assert",
    ]
    assert plan.steps_json[-1]["params"]["locator_bundle"] == locator_bundle


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


@pytest.fixture
def seeded_stateful_crawl_snapshot(db_session, seeded_system):
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
        page_summary="用户管理列表",
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
            element_text="启用用户列表",
            playwright_locator="get_by_role('table', name='启用用户列表')",
            state_signature="users:default",
            state_context={"active_tab": "enabled"},
            locator_candidates=[
                {"strategy_type": "semantic", "selector": "role=table[name='启用用户列表']"},
                {"strategy_type": "css", "selector": ".users-table"},
            ],
            usage_description="展示用户列表",
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            element_type="table",
            element_role="table",
            element_text="禁用用户列表",
            playwright_locator="get_by_role('table', name='禁用用户列表')",
            state_signature="users:tab=disabled",
            state_context={"active_tab": "disabled", "entry_type": "tab_switch"},
            locator_candidates=[
                {"strategy_type": "semantic", "selector": "role=table[name='禁用用户列表']"},
                {"strategy_type": "label", "selector": "label=禁用用户"},
            ],
            usage_description="展示禁用用户列表",
        )
    )
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


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


@pytest.mark.anyio
async def test_compile_snapshot_builds_state_signature_module_plan_with_locator_bundle(
    db_session,
    asset_compiler_service,
    seeded_stateful_crawl_snapshot,
):
    await asset_compiler_service.compile_snapshot(snapshot_id=seeded_stateful_crawl_snapshot.id)

    stateful_plan = db_session.exec(
        select(ModulePlan)
        .where(ModulePlan.check_code == "tab_switch_render")
        .order_by(ModulePlan.id.desc())
    ).first()

    assert stateful_plan is not None
    assert [step["module"] for step in stateful_plan.steps_json] == [
        "auth.inject_state",
        "nav.menu_chain",
        "page.wait_ready",
        "state.enter",
        "locator.assert",
    ]
    assert (
        stateful_plan.steps_json[-1]["params"]["locator_bundle"]["candidates"][0]["strategy_type"]
        == "semantic"
    )
    assert stateful_plan.steps_json[3]["params"]["state_signature"] == "users:tab=disabled"


def test_compile_snapshot_result_exposes_reconciliation_counts():
    assert "assets_retired" in CompileSnapshotResult.__dataclass_fields__
    assert "checks_retired" in CompileSnapshotResult.__dataclass_fields__
    assert "alias_disable_decision_count" in CompileSnapshotResult.__dataclass_fields__
    assert "alias_enable_decision_count" in CompileSnapshotResult.__dataclass_fields__
    assert "published_job_pause_decision_count" in CompileSnapshotResult.__dataclass_fields__
    assert "published_job_resume_decision_count" in CompileSnapshotResult.__dataclass_fields__
    assert "alias_ids_to_disable" in CompileSnapshotResult.__dataclass_fields__
    assert "alias_ids_to_enable" in CompileSnapshotResult.__dataclass_fields__
    assert "published_job_ids_to_pause" in CompileSnapshotResult.__dataclass_fields__
    assert "published_job_ids_to_resume" in CompileSnapshotResult.__dataclass_fields__
    assert "retire_reasons" in CompileSnapshotResult.__dataclass_fields__


def _build_asset_key(system_code: str, route_path: str) -> str:
    route_segments = [segment for segment in route_path.strip("/").split("/") if segment]
    if route_segments:
        return ".".join([system_code.lower(), *route_segments]).replace("-", "_")
    return f"{system_code.lower()}.page"


def _create_snapshot(
    db_session,
    seeded_system,
    *,
    crawl_type: str = "full",
    quality_score: float | None = 0.95,
    degraded: bool = False,
) -> CrawlSnapshot:
    snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type=crawl_type,
        framework_detected=seeded_system.framework_type,
        quality_score=quality_score,
        degraded=degraded,
    )
    db_session.add(snapshot)
    db_session.flush()
    return snapshot


def _add_page_fact(
    db_session,
    seeded_system,
    snapshot: CrawlSnapshot,
    *,
    route_path: str,
    page_title: str,
    page_summary: str = "列表页",
    menu_chain: list[str] | None = None,
    include_table: bool = True,
    include_button: bool = False,
) -> Page:
    page = Page(
        system_id=seeded_system.id,
        snapshot_id=snapshot.id,
        route_path=route_path,
        page_title=page_title,
        page_summary=page_summary,
    )
    db_session.add(page)
    db_session.flush()

    chain = menu_chain if menu_chain is not None else ["系统管理", page_title]
    for depth, label in enumerate(chain):
        db_session.add(
            MenuNode(
                system_id=seeded_system.id,
                snapshot_id=snapshot.id,
                page_id=page.id,
                label=label,
                route_path=route_path if depth == len(chain) - 1 else None,
                depth=depth,
                sort_order=1,
            )
        )

    if include_table:
        db_session.add(
            PageElement(
                system_id=seeded_system.id,
                snapshot_id=snapshot.id,
                page_id=page.id,
                element_type="table",
                element_role="table",
                element_text="列表",
                playwright_locator="get_by_role('table', name='列表')",
                usage_description="展示列表",
            )
        )
    if include_button:
        db_session.add(
            PageElement(
                system_id=seeded_system.id,
                snapshot_id=snapshot.id,
                page_id=page.id,
                element_type="button",
                element_role="button",
                element_text="新增用户",
                playwright_locator="get_by_role('button', name='新增用户')",
                usage_description="新增记录",
            )
        )

    db_session.flush()
    return page


@pytest.mark.anyio
async def test_compile_snapshot_retires_missing_page_after_high_quality_full_crawl(
    db_session,
    asset_compiler_service,
    seeded_system,
):
    baseline = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    baseline_pages = [
        ("/users", "用户管理"),
        ("/roles", "角色管理"),
        ("/logs", "操作日志"),
        ("/menus", "菜单管理"),
        ("/settings", "系统设置"),
    ]
    for route_path, page_title in baseline_pages:
        _add_page_fact(
            db_session,
            seeded_system,
            baseline,
            route_path=route_path,
            page_title=page_title,
            page_summary=f"{page_title}列表",
            include_table=True,
        )
    db_session.commit()

    await asset_compiler_service.compile_snapshot(snapshot_id=baseline.id)

    removed_asset_key = _build_asset_key(seeded_system.code, "/settings")
    removed_asset = db_session.exec(
        select(PageAsset).where(PageAsset.asset_key == removed_asset_key)
    ).one()
    removed_check = db_session.exec(
        select(PageCheck).where(PageCheck.page_asset_id == removed_asset.id)
    ).first()
    assert removed_check is not None

    db_session.add(
        PublishedJob(
            job_key="erp_settings_page_open",
            page_check_id=removed_check.id,
            asset_version=removed_asset.asset_version,
            runtime_policy="published",
            schedule_expr="*/5 * * * *",
            state=PublishedJobState.ACTIVE,
        )
    )
    db_session.commit()

    current = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    for route_path, page_title in baseline_pages[:-1]:
        _add_page_fact(
            db_session,
            seeded_system,
            current,
            route_path=route_path,
            page_title=page_title,
            page_summary=f"{page_title}列表",
            include_table=True,
        )
    db_session.commit()

    result = await asset_compiler_service.compile_snapshot(snapshot_id=current.id)

    assert result.assets_retired == 1
    assert result.checks_retired >= 1


@pytest.mark.anyio
async def test_compile_snapshot_skips_retirement_when_snapshot_is_degraded(
    db_session,
    asset_compiler_service,
    seeded_system,
):
    baseline = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    _add_page_fact(db_session, seeded_system, baseline, route_path="/users", page_title="用户管理")
    _add_page_fact(db_session, seeded_system, baseline, route_path="/roles", page_title="角色管理")
    db_session.commit()
    await asset_compiler_service.compile_snapshot(snapshot_id=baseline.id)

    degraded_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=True)
    _add_page_fact(
        db_session,
        seeded_system,
        degraded_snapshot,
        route_path="/users",
        page_title="用户管理",
    )
    db_session.commit()

    result = await asset_compiler_service.compile_snapshot(snapshot_id=degraded_snapshot.id)

    assert result.assets_retired == 0


@pytest.mark.anyio
async def test_compile_snapshot_retires_check_when_blocking_menu_chain_is_missing(
    db_session,
    asset_compiler_service,
    seeded_system,
):
    previous_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    previous_page = _add_page_fact(
        db_session,
        seeded_system,
        previous_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        include_table=False,
    )

    page_asset = PageAsset(
        system_id=seeded_system.id,
        page_id=previous_page.id,
        asset_key=_build_asset_key(seeded_system.code, "/users"),
        asset_version="baseline",
        status=AssetStatus.SAFE,
        lifecycle_status=AssetLifecycleStatus.ACTIVE,
        compiled_from_snapshot_id=previous_snapshot.id,
    )
    db_session.add(page_asset)
    db_session.flush()

    module_plan = ModulePlan(
        page_asset_id=page_asset.id,
        check_code="custom_menu_chain_guard",
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {
                "module": "nav.menu_chain",
                "params": {"menu_chain": ["系统管理", "用户管理"], "route_path": "/users"},
            },
            {"module": "assert.page_ready", "params": {}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    menu_guard_check = PageCheck(
        page_asset_id=page_asset.id,
        check_code="custom_menu_chain_guard",
        goal="custom_menu_chain_guard",
        lifecycle_status=AssetLifecycleStatus.ACTIVE,
        assertion_schema={"assertion": "page_ready"},
        module_plan_id=module_plan.id,
    )
    db_session.add(menu_guard_check)
    db_session.flush()
    menu_guard_alias = IntentAlias(
        system_alias=seeded_system.code,
        page_alias=previous_page.page_title,
        check_alias=menu_guard_check.check_code,
        route_hint=previous_page.route_path,
        asset_key=page_asset.asset_key,
        source="seed",
        is_active=True,
    )
    db_session.add(menu_guard_alias)
    db_session.commit()

    current_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    _add_page_fact(
        db_session,
        seeded_system,
        current_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["用户管理"],
        include_table=False,
    )
    db_session.commit()

    result = await asset_compiler_service.compile_snapshot(snapshot_id=current_snapshot.id)

    assert result.checks_retired == 1
    assert result.retire_reasons[0]["reason"] == "missing_menu_chain"
    assert result.alias_disable_decision_count == 1
    assert result.alias_ids_to_disable == [menu_guard_alias.id]


@pytest.mark.anyio
async def test_compile_snapshot_retires_check_when_key_element_is_missing(
    db_session,
    asset_compiler_service,
    seeded_system,
):
    previous_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    previous_page = _add_page_fact(
        db_session,
        seeded_system,
        previous_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        include_table=False,
        include_button=True,
    )

    page_asset = PageAsset(
        system_id=seeded_system.id,
        page_id=previous_page.id,
        asset_key=_build_asset_key(seeded_system.code, "/users"),
        asset_version="baseline",
        status=AssetStatus.SAFE,
        lifecycle_status=AssetLifecycleStatus.ACTIVE,
        compiled_from_snapshot_id=previous_snapshot.id,
    )
    db_session.add(page_asset)
    db_session.flush()

    module_plan = ModulePlan(
        page_asset_id=page_asset.id,
        check_code="custom_key_element_guard",
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {
                "module": "nav.menu_chain",
                "params": {"menu_chain": ["系统管理", "用户管理"], "route_path": "/users"},
            },
            {"module": "assert.page_ready", "params": {}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    key_element_guard_check = PageCheck(
        page_asset_id=page_asset.id,
        check_code="custom_key_element_guard",
        goal="custom_key_element_guard",
        lifecycle_status=AssetLifecycleStatus.ACTIVE,
        assertion_schema={
            "required_elements": [
                {"kind": "button", "text": "新增用户"},
            ]
        },
        module_plan_id=module_plan.id,
    )
    db_session.add(key_element_guard_check)
    db_session.flush()
    key_element_guard_alias = IntentAlias(
        system_alias=seeded_system.code,
        page_alias=previous_page.page_title,
        check_alias=key_element_guard_check.check_code,
        route_hint=previous_page.route_path,
        asset_key=page_asset.asset_key,
        source="seed",
        is_active=True,
    )
    db_session.add(key_element_guard_alias)
    db_session.commit()

    current_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    _add_page_fact(
        db_session,
        seeded_system,
        current_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        include_table=False,
        include_button=False,
    )
    db_session.commit()

    result = await asset_compiler_service.compile_snapshot(snapshot_id=current_snapshot.id)

    assert result.checks_retired == 1
    assert result.retire_reasons[0]["reason"] == "missing_key_element"
    assert result.alias_disable_decision_count == 1
    assert result.alias_ids_to_disable == [key_element_guard_alias.id]


@pytest.mark.anyio
async def test_compile_snapshot_reactivates_retired_asset_when_high_quality_full_crawl_finds_it_again(
    db_session,
    asset_compiler_service,
    seeded_system,
):
    retired_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    retired_page = _add_page_fact(
        db_session,
        seeded_system,
        retired_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        include_table=True,
    )

    retired_asset = PageAsset(
        system_id=seeded_system.id,
        page_id=retired_page.id,
        asset_key=_build_asset_key(seeded_system.code, "/users"),
        asset_version="stale-version",
        status=AssetStatus.SAFE,
        lifecycle_status=AssetLifecycleStatus.RETIRED_MISSING,
        retired_reason="missing_page",
        retired_by_snapshot_id=retired_snapshot.id,
        compiled_from_snapshot_id=retired_snapshot.id,
    )
    db_session.add(retired_asset)
    db_session.flush()

    module_plan = ModulePlan(
        page_asset_id=retired_asset.id,
        check_code="page_open",
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {
                "module": "nav.menu_chain",
                "params": {"menu_chain": ["系统管理", "用户管理"], "route_path": "/users"},
            },
            {"module": "assert.page_ready", "params": {}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    retired_page_open_check = PageCheck(
        page_asset_id=retired_asset.id,
        check_code="page_open",
        goal="page_open",
        lifecycle_status=AssetLifecycleStatus.RETIRED_MISSING,
        retired_reason="missing_page",
        retired_by_snapshot_id=retired_snapshot.id,
        assertion_schema={"assertion": "page_ready"},
        module_plan_id=module_plan.id,
    )
    db_session.add(retired_page_open_check)
    db_session.flush()
    retired_alias = IntentAlias(
        system_alias=seeded_system.code,
        page_alias=retired_page.page_title,
        check_alias=retired_page_open_check.check_code,
        route_hint=retired_page.route_path,
        asset_key=retired_asset.asset_key,
        confidence=1.0,
        source="asset_compiler",
        is_active=False,
        disabled_reason="retired_missing",
        disabled_by_snapshot_id=retired_snapshot.id,
    )
    db_session.add(retired_alias)
    manually_disabled_alias = IntentAlias(
        system_alias=seeded_system.code,
        page_alias=retired_page.page_title,
        check_alias=retired_page_open_check.check_code,
        route_hint=retired_page.route_path,
        asset_key=retired_asset.asset_key,
        confidence=1.0,
        source="manual",
        is_active=False,
        disabled_reason="manual_disabled",
        disabled_by_snapshot_id=None,
    )
    db_session.add(manually_disabled_alias)
    paused_job = PublishedJob(
        job_key="erp_users_page_open",
        page_check_id=retired_page_open_check.id,
        asset_version=retired_asset.asset_version,
        runtime_policy="published",
        schedule_expr="*/5 * * * *",
        state=PublishedJobState.PAUSED,
        pause_reason="asset_retired_missing",
        paused_by_snapshot_id=retired_snapshot.id,
        paused_by_asset_id=retired_asset.id,
        paused_by_page_check_id=retired_page_open_check.id,
    )
    db_session.add(paused_job)
    manually_paused_job = PublishedJob(
        job_key="erp_users_page_open_manual",
        page_check_id=retired_page_open_check.id,
        asset_version=retired_asset.asset_version,
        runtime_policy="published",
        schedule_expr="*/10 * * * *",
        state=PublishedJobState.PAUSED,
        pause_reason="manual_pause",
        paused_by_snapshot_id=None,
        paused_by_asset_id=None,
        paused_by_page_check_id=None,
    )
    db_session.add(manually_paused_job)
    db_session.commit()

    current_snapshot = _create_snapshot(db_session, seeded_system, quality_score=0.95, degraded=False)
    _add_page_fact(
        db_session,
        seeded_system,
        current_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        include_table=True,
    )
    db_session.commit()

    result = await asset_compiler_service.compile_snapshot(snapshot_id=current_snapshot.id)
    db_session.refresh(retired_asset)
    db_session.refresh(retired_alias)
    restored_page_open_check = db_session.exec(
        select(PageCheck)
        .where(PageCheck.page_asset_id == retired_asset.id)
        .where(PageCheck.check_code == "page_open")
    ).one()
    reconciliation_audit = db_session.exec(
        select(AssetReconciliationAudit)
        .where(AssetReconciliationAudit.snapshot_id == current_snapshot.id)
    ).one()

    assert result.assets_updated >= 1
    assert retired_asset.lifecycle_status == AssetLifecycleStatus.ACTIVE
    assert retired_asset.retired_reason is None
    assert retired_asset.retired_at is None
    assert retired_asset.retired_by_snapshot_id is None
    assert restored_page_open_check.lifecycle_status == AssetLifecycleStatus.ACTIVE
    assert restored_page_open_check.retired_reason is None
    assert restored_page_open_check.retired_at is None
    assert restored_page_open_check.retired_by_snapshot_id is None
    assert retired_alias.is_active is False
    assert retired_alias.disabled_reason == "retired_missing"
    assert retired_alias.disabled_at is None
    assert retired_alias.disabled_by_snapshot_id == retired_snapshot.id
    assert result.alias_enable_decision_count == 1
    assert result.alias_ids_to_enable == [retired_alias.id]
    assert manually_disabled_alias.id not in result.alias_ids_to_enable
    assert result.published_job_resume_decision_count == 1
    assert result.published_job_ids_to_resume == [paused_job.id]
    assert manually_paused_job.id not in result.published_job_ids_to_resume
    assert reconciliation_audit.enabled_alias_ids == [str(retired_alias.id)]
    assert reconciliation_audit.resumed_published_job_ids == [str(paused_job.id)]
