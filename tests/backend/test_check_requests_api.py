from sqlmodel import select

from app.infrastructure.db.models.execution import ExecutionPlan
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


def test_post_check_requests_accepts_template_payload(client, seeded_asset):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "ERP",
            "page_hint": "用户管理",
            "check_goal": "table_render",
            "template_code": "field_equals_exists",
            "template_version": "v1",
            "carrier_hint": "table",
            "template_params": {"field": "username", "operator": "equals", "value": "alice"},
        },
    )
    assert response.status_code == 202


def test_post_check_requests_rejects_template_payload_without_required_metadata(client, seeded_asset):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "ERP",
            "page_hint": "用户管理",
            "check_goal": "table_render",
            "template_params": {"field": "username", "operator": "equals", "value": "alice"},
        },
    )

    assert response.status_code == 422
    assert "template metadata is incomplete" in response.text


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


def test_get_check_request_result_returns_empty_summary_when_not_executed(
    client,
    accepted_request,
):
    response = client.get(f"/api/v1/check-requests/{accepted_request.request_id}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == str(accepted_request.request_id)
    assert body["plan_id"] == str(accepted_request.plan_id)
    assert body["execution_track"] == "precompiled"
    assert body["execution_summary"] is None
    assert body["artifacts"] == []
    assert body["needs_recrawl"] is False
    assert body["needs_recompile"] is False


def test_get_check_request_returns_404_for_missing_request(client):
    response = client.get("/api/v1/check-requests/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 404


def test_post_check_requests_uses_realtime_probe_when_page_or_menu_unresolved(
    client,
    seeded_system,
    db_session,
):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "ERP",
            "page_hint": "不存在的页面",
            "check_goal": "page_open",
        },
    )

    assert response.status_code == 202
    assert response.json()["execution_track"] == "realtime_probe"
    plan = db_session.exec(select(ExecutionPlan)).one()
    assert plan.resolved_system_id == seeded_system.id
    assert plan.resolved_page_asset_id is None


def test_post_check_requests_returns_409_when_element_asset_missing(
    client,
    seeded_asset_without_matching_check,
):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "WMS",
            "page_hint": "库存列表",
            "check_goal": "table_render",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "element asset is missing"
