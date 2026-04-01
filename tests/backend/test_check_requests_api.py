from sqlmodel import select

from app.infrastructure.db.models.jobs import QueuedJob


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


def test_post_check_requests_rejects_non_positive_time_budget(client, db_session):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "ERP",
            "check_goal": "table_render",
            "time_budget_ms": 0,
        },
    )

    assert response.status_code == 422
    assert db_session.exec(select(QueuedJob)).all() == []

def test_get_check_request_returns_status(client, accepted_request, db_session):
    queued_job = db_session.exec(select(QueuedJob)).one()
    queued_job.status = "queued"
    db_session.add(queued_job)
    db_session.commit()

    response = client.get(f"/api/v1/check-requests/{accepted_request.request_id}")

    assert response.status_code == 200
    assert response.json()["request_id"] == str(accepted_request.request_id)
    assert response.json()["status"] == "queued"
    assert response.json()["execution_track"] == "precompiled"


def test_get_check_request_returns_404_for_missing_request(client):
    response = client.get("/api/v1/check-requests/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 404
