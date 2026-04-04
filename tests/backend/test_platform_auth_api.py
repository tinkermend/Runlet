from typing import Any, Dict

from fastapi.testclient import TestClient


def _auth_cookie(client: TestClient) -> Dict[str, str]:
    resp = client.post(
        "/api/console/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert resp.status_code == 200
    token = resp.cookies.get("console_session")
    assert token
    return {"console_session": token}


def _create_pat(client: TestClient, cookies: Dict[str, str]) -> Dict[str, Any]:
    resp = client.post(
        "/api/v1/platform-auth/pats",
        json={"name": "test-skill", "expires_in_days": 3},
        cookies=cookies,
    )
    assert resp.status_code == 201
    return resp.json()


def test_create_pat_returns_plaintext_once(client: TestClient) -> None:
    cookies = _auth_cookie(client)
    payload = _create_pat(client, cookies)
    assert payload["name"] == "test-skill"
    assert payload["token"].startswith("rpat_")

    list_resp = client.get("/api/v1/platform-auth/pats", cookies=cookies)
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert any(entry["id"] == payload["id"] for entry in entries)
    assert all("token" not in entry for entry in entries)


def test_create_pat_rejects_invalid_ttl(client: TestClient) -> None:
    cookies = _auth_cookie(client)
    resp = client.post(
        "/api/v1/platform-auth/pats",
        json={"name": "illegal-ttl", "expires_in_days": 5},
        cookies=cookies,
    )
    assert resp.status_code == 422


def test_revoke_pat_blocks_future_use(client: TestClient) -> None:
    cookies = _auth_cookie(client)
    pat = _create_pat(client, cookies)
    pat_id = pat["id"]

    revoke_resp = client.post(
        f"/api/v1/platform-auth/pats/{pat_id}:revoke",
        cookies=cookies,
    )
    assert revoke_resp.status_code == 204

    list_resp = client.get("/api/v1/platform-auth/pats", cookies=cookies)
    assert list_resp.status_code == 200
    entry = next(entry for entry in list_resp.json() if entry["id"] == pat_id)
    assert entry["revoked_at"] is not None
