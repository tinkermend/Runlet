from fastapi.testclient import TestClient

from app.main import create_app


def test_app_boots_with_health_router():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_error_responses_preserve_underlying_exception_type():
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise ModuleNotFoundError("psycopg2")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error_type"] == "ModuleNotFoundError"
