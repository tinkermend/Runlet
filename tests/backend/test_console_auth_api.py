from fastapi.testclient import TestClient


def test_login_success(client: TestClient):
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "console_session" in resp.cookies


def test_login_wrong_password(client: TestClient):
    resp = client.post("/api/console/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_logout(client: TestClient):
    client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.post("/api/console/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_me_authenticated(client: TestClient):
    client.post("/api/console/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.get("/api/console/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_me_unauthenticated(client: TestClient):
    resp = client.get("/api/console/auth/me")
    assert resp.status_code == 401
