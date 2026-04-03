from fastapi.testclient import TestClient

from app.main import create_app


def make_client() -> TestClient:
    app = create_app()
    return TestClient(app, raise_server_exceptions=True)


def test_login_success():
    client = make_client()
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "console_session" in resp.cookies


def test_login_wrong_password():
    client = make_client()
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_logout():
    client = make_client()
    client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.post("/api/console/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_me_authenticated():
    client = make_client()
    client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.get("/api/console/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_me_unauthenticated():
    client = make_client()
    resp = client.get("/api/console/auth/me")
    assert resp.status_code == 401
