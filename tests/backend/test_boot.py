from fastapi.testclient import TestClient

from app.main import create_app


def test_app_boots_with_health_router():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
