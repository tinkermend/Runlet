from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _login(client: TestClient) -> None:
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200


def test_results_requires_auth(client: TestClient):
    resp = client.get("/api/console/results/")
    assert resp.status_code == 401


def test_results_list(client: TestClient):
    """Results list returns paginated response."""
    _login(client)
    resp = client.get("/api/console/results/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data


def test_results_list_with_filters(client: TestClient):
    """Results list accepts filter params."""
    _login(client)
    resp = client.get("/api/console/results/?page=1&page_size=10")
    assert resp.status_code == 200
