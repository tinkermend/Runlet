from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _login(client: TestClient) -> None:
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200


def test_tasks_requires_auth(client: TestClient):
    resp = client.get("/api/console/tasks/")
    assert resp.status_code == 401


def test_tasks_list(client: TestClient):
    """Task list returns array."""
    _login(client)
    resp = client.get("/api/console/tasks/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_task_create(client: TestClient):
    """Create a new task."""
    _login(client)
    sys_resp = client.post("/api/console/portal/systems", json={
        "name": "Task Test System",
        "base_url": "https://example.com",
        "auth_type": "none",
    })
    assert sys_resp.status_code in (200, 201)
    system_id = sys_resp.json()["id"]

    resp = client.post("/api/console/tasks/", json={
        "name": "Test Task",
        "system_id": system_id,
        "check_types": ["menu_completeness"],
        "schedule_preset": "manual",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "id" in data
    assert data["name"] == "Test Task"


def test_task_detail(client: TestClient):
    """Get task detail."""
    _login(client)
    sys_resp = client.post("/api/console/portal/systems", json={
        "name": "Detail Test System",
        "base_url": "https://example.com",
        "auth_type": "none",
    })
    system_id = sys_resp.json()["id"]

    create_resp = client.post("/api/console/tasks/", json={
        "name": "Detail Test Task",
        "system_id": system_id,
        "check_types": ["menu_completeness"],
        "schedule_preset": "manual",
    })
    task_id = create_resp.json()["id"]

    resp = client.get(f"/api/console/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["name"] == "Detail Test Task"
    assert "recent_runs" in data


def test_task_trigger(client: TestClient):
    """Trigger a task run."""
    _login(client)
    sys_resp = client.post("/api/console/portal/systems", json={
        "name": "Trigger Test System",
        "base_url": "https://example.com",
        "auth_type": "none",
    })
    system_id = sys_resp.json()["id"]

    create_resp = client.post("/api/console/tasks/", json={
        "name": "Trigger Test Task",
        "system_id": system_id,
        "check_types": ["menu_completeness"],
        "schedule_preset": "manual",
    })
    task_id = create_resp.json()["id"]

    resp = client.post(f"/api/console/tasks/{task_id}/trigger")
    assert resp.status_code in (200, 202)
    data = resp.json()
    assert "ok" in data


def test_task_wizard_options(client: TestClient):
    """Wizard options returns systems and check types."""
    _login(client)
    resp = client.get("/api/console/tasks/wizard-options")
    assert resp.status_code == 200
    data = resp.json()
    assert "systems" in data
    assert "check_types" in data
    assert isinstance(data["check_types"], list)
