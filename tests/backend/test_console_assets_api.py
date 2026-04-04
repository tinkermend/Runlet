from __future__ import annotations

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
