from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_results_list(client: TestClient):
    """Results list returns paginated response."""
    resp = client.get("/api/console/results/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data


def test_results_list_with_filters(client: TestClient):
    """Results list accepts filter params."""
    resp = client.get("/api/console/results/?page=1&page_size=10")
    assert resp.status_code == 200
