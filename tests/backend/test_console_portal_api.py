from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _login(client: TestClient) -> None:
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200


def test_dashboard_requires_auth(client: TestClient):
    resp = client.get("/api/console/portal/dashboard")
    assert resp.status_code == 401


def test_dashboard_summary(client: TestClient):
    """Dashboard summary returns counts."""
    _login(client)
    resp = client.get("/api/console/portal/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "today_runs" in data
    assert "active_tasks" in data
    assert "systems_count" in data
    assert "recent_failures_24h" in data
    assert "recent_exceptions" in data
    assert isinstance(data["recent_exceptions"], list)


def test_systems_list(client: TestClient):
    """Systems list returns array."""
    _login(client)
    resp = client.get("/api/console/portal/systems")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_system_onboard(client: TestClient):
    """Onboard a new system."""
    _login(client)
    resp = client.post("/api/console/portal/systems", json={
        "name": "Test System",
        "base_url": "https://example.com",
        "auth_type": "none",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "id" in data
    assert data["name"] == "Test System"
