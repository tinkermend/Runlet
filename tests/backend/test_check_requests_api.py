import anyio
import pytest


def test_post_check_requests_returns_accepted(client, seeded_asset):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "ERP",
            "page_hint": "用户管理",
            "check_goal": "table_render",
            "strictness": "balanced",
            "time_budget_ms": 20000,
            "request_source": "skill",
        },
    )

    assert response.status_code == 202
    assert response.json()["execution_track"] == "precompiled"


@pytest.fixture
def accepted_request(control_plane_service, seeded_asset):
    async def submit():
        return await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="table_render",
            strictness="balanced",
            time_budget_ms=20_000,
            request_source="skill",
        )

    return anyio.run(submit)


def test_get_check_request_returns_status(client, accepted_request):
    response = client.get(f"/api/v1/check-requests/{accepted_request.request_id}")

    assert response.status_code == 200
    assert response.json()["request_id"] == str(accepted_request.request_id)
