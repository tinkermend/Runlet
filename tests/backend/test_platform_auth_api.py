from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.infrastructure.security.pat_auth import get_pat_for_token


def _auth_cookie(client: TestClient) -> Dict[str, str]:
    resp = client.post(
        "/api/console/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert resp.status_code == 200
    token = resp.cookies.get("console_session")
    assert token
    return {"console_session": token}


def _create_pat(client: TestClient, cookies: Dict[str, str], expires_in_days: int) -> Dict[str, Any]:
    resp = client.post(
        "/api/v1/platform-auth/pats",
        json={"name": f"test-skill-{expires_in_days}", "expires_in_days": expires_in_days},
        cookies=cookies,
    )
    assert resp.status_code == 201
    return resp.json()


def _assert_within_ttl(issue: str, expiry: str, expected_days: int) -> None:
    issue_dt = datetime.fromisoformat(issue)
    expiry_dt = datetime.fromisoformat(expiry)
    diff = expiry_dt - issue_dt
    assert timedelta(days=expected_days - 0.5) <= diff <= timedelta(days=expected_days + 0.5)


def test_create_pat_returns_plaintext_once(client: TestClient) -> None:
    cookies = _auth_cookie(client)
    payload = _create_pat(client, cookies, expires_in_days=3)
    assert payload["name"].endswith("-3")
    assert payload["token"].startswith("rpat_")
    _assert_within_ttl(payload["issued_at"], payload["expires_at"], expected_days=3)

    list_resp = client.get("/api/v1/platform-auth/pats", cookies=cookies)
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert any(entry["id"] == payload["id"] for entry in entries)
    assert all("token" not in entry for entry in entries)


def test_create_pat_allows_7_day_ttl(client: TestClient) -> None:
    cookies = _auth_cookie(client)
    payload = _create_pat(client, cookies, expires_in_days=7)
    assert payload["name"].endswith("-7")
    _assert_within_ttl(payload["issued_at"], payload["expires_at"], expected_days=7)


def test_create_pat_rejects_invalid_ttl(client: TestClient) -> None:
    cookies = _auth_cookie(client)
    resp = client.post(
        "/api/v1/platform-auth/pats",
        json={"name": "illegal-ttl", "expires_in_days": 5},
        cookies=cookies,
    )
    assert resp.status_code == 422


def test_revoked_pat_token_is_invalid(client: TestClient, db_session: Session) -> None:
    cookies = _auth_cookie(client)
    payload = _create_pat(client, cookies, expires_in_days=3)
    token = payload["token"]
    revoke_resp = client.post(
        f"/api/v1/platform-auth/pats/{payload['id']}:revoke",
        cookies=cookies,
    )
    assert revoke_resp.status_code == 204

    assert get_pat_for_token(token=token, session=db_session) is None
