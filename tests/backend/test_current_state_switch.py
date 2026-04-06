from sqlmodel import select

import pytest
import sqlalchemy as sa

from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
from app.infrastructure.db.models.crawl_history import CrawlSnapshotHist


def _create_snapshot(
    db_session,
    seeded_system,
    *,
    quality_score: float | None = 0.95,
    degraded: bool = False,
    state: str = "draft",
) -> CrawlSnapshot:
    snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
        quality_score=quality_score,
        degraded=degraded,
        state=state,
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
    menu_chain: list[str],
    table_text: str,
    state_signature: str | None = None,
    state_context: dict[str, object] | None = None,
) -> Page:
    page = Page(
        system_id=seeded_system.id,
        snapshot_id=snapshot.id,
        route_path=route_path,
        page_title=page_title,
        page_summary=f"{page_title}列表",
    )
    db_session.add(page)
    db_session.flush()

    for depth, label in enumerate(menu_chain):
        db_session.add(
            MenuNode(
                system_id=seeded_system.id,
                snapshot_id=snapshot.id,
                page_id=page.id,
                label=label,
                route_path=route_path if depth == len(menu_chain) - 1 else None,
                depth=depth,
                sort_order=depth + 1,
            )
        )

    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=snapshot.id,
            page_id=page.id,
            element_type="table",
            element_role="table",
            element_text=table_text,
            playwright_locator=f"get_by_role('table', name='{table_text}')",
            state_signature=state_signature,
            state_context=state_context,
            usage_description="展示列表",
        )
    )
    db_session.flush()
    return page


@pytest.mark.anyio
async def test_apply_current_state_switch_discards_draft_when_semantics_match_active(
    db_session,
    seeded_system,
):
    from app.domains.asset_compiler.current_state_switch import apply_current_state_switch

    active_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        active_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
    )

    draft_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="draft",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        draft_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
    )
    db_session.commit()

    result = await apply_current_state_switch(
        session=db_session,
        draft_snapshot_id=draft_snapshot.id,
    )
    db_session.refresh(active_snapshot)
    db_session.refresh(draft_snapshot)

    assert result.outcome == "discarded_no_change"
    assert active_snapshot.state == "active"
    assert draft_snapshot.state == "discarded"
    assert draft_snapshot.discarded_at is not None
    assert db_session.exec(select(CrawlSnapshotHist)).all() == []


@pytest.mark.anyio
async def test_apply_current_state_switch_promotes_draft_and_archives_previous_active_on_change(
    db_session,
    seeded_system,
):
    from app.domains.asset_compiler.current_state_switch import apply_current_state_switch

    active_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        active_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
    )

    draft_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="draft",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        draft_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户清单",
    )
    db_session.commit()

    result = await apply_current_state_switch(
        session=db_session,
        draft_snapshot_id=draft_snapshot.id,
    )
    db_session.refresh(active_snapshot)
    db_session.refresh(draft_snapshot)
    archived_rows = db_session.exec(select(CrawlSnapshotHist)).all()

    assert result.outcome == "promoted"
    assert active_snapshot.state == "discarded"
    assert active_snapshot.discarded_at is not None
    assert draft_snapshot.state == "active"
    assert draft_snapshot.activated_at is not None
    assert len(archived_rows) == 1
    assert archived_rows[0].snapshot_id == active_snapshot.id
    assert archived_rows[0].source_active_snapshot_id == active_snapshot.id
    assert archived_rows[0].replaced_by_snapshot_id == draft_snapshot.id


@pytest.mark.anyio
async def test_apply_current_state_switch_promotes_when_only_state_signature_changes(
    db_session,
    seeded_system,
):
    from app.domains.asset_compiler.current_state_switch import apply_current_state_switch

    active_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        active_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
        state_signature="users:default",
        state_context={"entry_type": "default"},
    )

    draft_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="draft",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        draft_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
        state_signature="users:tab=disabled",
        state_context={"entry_type": "tab_switch", "active_tab": "disabled"},
    )
    db_session.commit()

    result = await apply_current_state_switch(
        session=db_session,
        draft_snapshot_id=draft_snapshot.id,
    )
    db_session.refresh(active_snapshot)
    db_session.refresh(draft_snapshot)

    assert result.outcome == "promoted"
    assert active_snapshot.state == "discarded"
    assert draft_snapshot.state == "active"


@pytest.mark.anyio
async def test_apply_current_state_switch_discards_low_quality_draft_without_touching_active(
    db_session,
    seeded_system,
):
    from app.domains.asset_compiler.current_state_switch import apply_current_state_switch

    active_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        active_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
    )

    degraded_draft = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=True,
        state="draft",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        degraded_draft,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
    )
    db_session.commit()

    result = await apply_current_state_switch(
        session=db_session,
        draft_snapshot_id=degraded_draft.id,
    )
    db_session.refresh(active_snapshot)
    db_session.refresh(degraded_draft)

    assert result.outcome == "discarded_low_quality"
    assert active_snapshot.state == "active"
    assert degraded_draft.state == "discarded"
    assert degraded_draft.discarded_at is not None
    assert db_session.exec(select(CrawlSnapshotHist)).all() == []


@pytest.mark.anyio
async def test_apply_current_state_switch_discards_unscored_draft_without_touching_active(
    db_session,
    seeded_system,
):
    from app.domains.asset_compiler.current_state_switch import apply_current_state_switch

    active_snapshot = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        active_snapshot,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户列表",
    )

    unscored_draft = _create_snapshot(
        db_session,
        seeded_system,
        quality_score=None,
        degraded=False,
        state="draft",
    )
    _add_page_fact(
        db_session,
        seeded_system,
        unscored_draft,
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        table_text="用户清单",
    )
    db_session.commit()

    result = await apply_current_state_switch(
        session=db_session,
        draft_snapshot_id=unscored_draft.id,
    )
    db_session.refresh(active_snapshot)
    db_session.refresh(unscored_draft)

    assert result.outcome == "discarded_low_quality"
    assert active_snapshot.state == "active"
    assert unscored_draft.state == "discarded"
    assert unscored_draft.discarded_at is not None


def test_crawl_snapshot_allows_only_one_active_snapshot_per_system(
    db_session,
    seeded_system,
):
    db_session.add(
        CrawlSnapshot(
            system_id=seeded_system.id,
            crawl_type="full",
            framework_detected=seeded_system.framework_type,
            quality_score=0.95,
            degraded=False,
            state="active",
        )
    )
    db_session.commit()

    db_session.add(
        CrawlSnapshot(
            system_id=seeded_system.id,
            crawl_type="full",
            framework_detected=seeded_system.framework_type,
            quality_score=0.95,
            degraded=False,
            state="active",
        )
    )

    with pytest.raises(sa.exc.IntegrityError):
        db_session.commit()
    db_session.rollback()
