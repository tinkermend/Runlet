from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


def _login(client: TestClient) -> None:
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200


def test_assets_requires_auth(client: TestClient):
    resp = client.get("/api/console/assets/")
    assert resp.status_code == 401


def test_assets_list_empty(client: TestClient):
    """Asset list returns an empty list when no assets exist."""
    _login(client)
    resp = client.get("/api/console/assets/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_assets_list_with_seeded_asset(client: TestClient, seeded_page_asset):
    """Asset list returns grouped structure when assets exist."""
    _login(client)
    resp = client.get("/api/console/assets/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    group = data[0]
    assert "system_id" in group
    assert "system_name" in group
    assert "pages" in group
    assert isinstance(group["pages"], list)
    assert len(group["pages"]) >= 1

    page_group = group["pages"][0]
    assert "page_name" in page_group
    assert "assets" in page_group
    assert isinstance(page_group["assets"], list)
    assert len(page_group["assets"]) >= 1

    asset_item = page_group["assets"][0]
    assert "id" in asset_item
    assert "check_type_label" in asset_item
    assert "version" in asset_item
    assert "status" in asset_item


def test_asset_detail_not_found(client: TestClient):
    """Asset detail returns 404 for unknown ID."""
    _login(client)
    resp = client.get("/api/console/assets/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_asset_detail(client: TestClient, seeded_page_asset):
    """Asset detail returns full info including raw_facts field."""
    _login(client)
    asset_id = str(seeded_page_asset.id)
    resp = client.get(f"/api/console/assets/{asset_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["id"] == asset_id
    assert "page_name" in data
    assert "system_name" in data
    assert "check_type_label" in data
    assert "version" in data
    assert "status" in data
    assert "raw_facts" in data  # may be None if no menu nodes / elements


def test_asset_detail_via_task_creation(client: TestClient):
    """Create a system + task, then verify asset appears in list and detail."""
    _login(client)
    sys_resp = client.post(
        "/api/console/portal/systems",
        json={
            "name": "Asset Test System",
            "base_url": "https://example.com",
            "auth_type": "none",
        },
    )
    assert sys_resp.status_code == 201
    system_id = sys_resp.json()["id"]

    task_resp = client.post(
        "/api/console/tasks/",
        json={
            "name": "Asset Test Task",
            "system_id": system_id,
            "check_types": ["menu_completeness"],
            "schedule_preset": "manual",
        },
    )
    assert task_resp.status_code == 201

    list_resp = client.get("/api/console/assets/")
    assert list_resp.status_code == 200
    assets = list_resp.json()

    asset_id = None
    for system_group in assets:
        for page_group in system_group.get("pages", []):
            for asset in page_group.get("assets", []):
                asset_id = asset["id"]
                break

    assert asset_id is not None, "Expected at least one asset after task creation"

    detail_resp = client.get(f"/api/console/assets/{asset_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == asset_id
    assert "check_type_label" in detail
    assert "raw_facts" in detail


def test_console_asset_detail_uses_active_page_facts_only(client: TestClient, db_session, seeded_system):
    from app.infrastructure.db.models.assets import PageAsset, PageCheck
    from app.infrastructure.db.models.crawl import CrawlSnapshot, MenuNode, Page, PageElement
    from app.shared.enums import AssetStatus

    active_snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    db_session.add(active_snapshot)
    db_session.flush()

    active_page = Page(
        system_id=seeded_system.id,
        snapshot_id=active_snapshot.id,
        route_path="/users",
        page_title="当前正式页面",
        page_summary="当前正式页",
        crawled_at=datetime(2026, 4, 6, 13, 0, tzinfo=UTC),
    )
    db_session.add(active_page)
    db_session.flush()

    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=active_snapshot.id,
            page_id=active_page.id,
            label="当前正式菜单",
            route_path="/users",
            depth=0,
            sort_order=1,
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=active_snapshot.id,
            page_id=active_page.id,
            element_type="table",
            element_role="table",
            element_text="当前正式元素",
            playwright_locator="role=table[name='当前正式元素']",
        )
    )

    discarded_snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
        quality_score=0.95,
        degraded=False,
        state="discarded",
    )
    db_session.add(discarded_snapshot)
    db_session.flush()

    discarded_page = Page(
        system_id=seeded_system.id,
        snapshot_id=discarded_snapshot.id,
        route_path="/users",
        page_title="废弃候选页面",
        page_summary="废弃候选页",
        crawled_at=datetime(2026, 4, 5, 13, 0, tzinfo=UTC),
    )
    db_session.add(discarded_page)
    db_session.flush()

    db_session.add(
        MenuNode(
            system_id=seeded_system.id,
            snapshot_id=discarded_snapshot.id,
            page_id=discarded_page.id,
            label="废弃候选菜单",
            route_path="/users",
            depth=0,
            sort_order=1,
        )
    )
    db_session.add(
        PageElement(
            system_id=seeded_system.id,
            snapshot_id=discarded_snapshot.id,
            page_id=discarded_page.id,
            element_type="table",
            element_role="table",
            element_text="废弃候选元素",
            playwright_locator="role=table[name='废弃候选元素']",
        )
    )

    asset = PageAsset(
        system_id=seeded_system.id,
        page_id=discarded_page.id,
        asset_key="erp.users",
        asset_version="2026.04.06",
        status=AssetStatus.SAFE,
        compiled_from_snapshot_id=discarded_snapshot.id,
    )
    db_session.add(asset)
    db_session.flush()
    db_session.add(
        PageCheck(
            page_asset_id=asset.id,
            check_code="table_render",
            goal="table_render",
        )
    )
    db_session.commit()

    _login(client)
    response = client.get(f"/api/console/assets/{asset.id}")
    assert response.status_code == 200
    payload = response.json()

    assert payload["raw_facts"] is not None
    assert payload["page_name"] == "当前正式页面"
    assert payload["collected_at"] == "2026-04-06T13:00:00"
    assert [item["label"] for item in payload["raw_facts"]["menu_nodes"]] == ["当前正式菜单"]
    assert [item["element_text"] for item in payload["raw_facts"]["page_elements"]] == ["当前正式元素"]


def test_console_assets_list_uses_active_page_name_only(client: TestClient, db_session, seeded_system):
    from app.infrastructure.db.models.assets import PageAsset, PageCheck
    from app.infrastructure.db.models.crawl import CrawlSnapshot, Page
    from app.shared.enums import AssetStatus

    active_snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
        quality_score=0.95,
        degraded=False,
        state="active",
    )
    db_session.add(active_snapshot)
    db_session.flush()

    active_page = Page(
        system_id=seeded_system.id,
        snapshot_id=active_snapshot.id,
        route_path="/users",
        page_title="当前正式页面",
    )
    db_session.add(active_page)
    db_session.flush()

    discarded_snapshot = CrawlSnapshot(
        system_id=seeded_system.id,
        crawl_type="full",
        framework_detected=seeded_system.framework_type,
        quality_score=0.95,
        degraded=False,
        state="discarded",
    )
    db_session.add(discarded_snapshot)
    db_session.flush()

    discarded_page = Page(
        system_id=seeded_system.id,
        snapshot_id=discarded_snapshot.id,
        route_path="/users",
        page_title="废弃候选页面",
    )
    db_session.add(discarded_page)
    db_session.flush()

    asset = PageAsset(
        system_id=seeded_system.id,
        page_id=discarded_page.id,
        asset_key="erp.users",
        asset_version="2026.04.06",
        status=AssetStatus.SAFE,
        compiled_from_snapshot_id=discarded_snapshot.id,
    )
    db_session.add(asset)
    db_session.flush()
    db_session.add(
        PageCheck(
            page_asset_id=asset.id,
            check_code="table_render",
            goal="table_render",
        )
    )
    db_session.commit()

    _login(client)
    response = client.get("/api/console/assets/")
    assert response.status_code == 200
    payload = response.json()

    assert payload[0]["pages"][0]["page_name"] == "当前正式页面"
