from __future__ import annotations

import anyio
import pytest
from sqlmodel import select
from uuid import UUID

from app.domains.runner_service.script_renderer import ScriptRenderer
from app.infrastructure.db.models.execution import ExecutionPlan, ExecutionRun, ScriptRender
from app.infrastructure.db.models.jobs import PublishedJob


@pytest.fixture
def completed_check_request(control_plane_service, db_session, seeded_schedulable_check):
    async def submit():
        return await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="table_render",
            strictness="balanced",
            time_budget_ms=20_000,
            request_source="skill",
        )

    accepted = anyio.run(submit)
    plan = db_session.get(ExecutionPlan, accepted.plan_id)
    assert plan is not None

    execution_run = ExecutionRun(
        execution_plan_id=plan.id,
        status="passed",
        duration_ms=1234,
        auth_status="reused",
        failure_category=None,
        asset_version="2026.04.01",
    )
    db_session.add(execution_run)
    db_session.commit()
    return accepted


def test_publish_successful_execution_creates_published_job(
    client,
    completed_check_request,
    db_session,
):
    response = client.post(
        f"/api/v1/check-requests/{completed_check_request.request_id}:publish",
        json={"schedule_expr": "0 */2 * * *"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["published_job_id"]
    assert body["page_check_id"] == str(completed_check_request.page_check_id)
    assert body["schedule_expr"] == "0 */2 * * *"
    published_job = db_session.get(PublishedJob, UUID(body["published_job_id"]))
    assert published_job is not None
    assert published_job.page_check_id == completed_check_request.page_check_id


def test_publish_fails_when_request_has_no_successful_execution(client, accepted_request):
    response = client.post(
        f"/api/v1/check-requests/{accepted_request.request_id}:publish",
        json={"schedule_expr": "0 */2 * * *"},
    )

    assert response.status_code == 409


def test_publish_reuses_existing_published_script_render(
    client,
    completed_check_request,
    db_session,
):
    existing = anyio.run(
        lambda: ScriptRenderer(session=db_session).render_page_check(
            page_check_id=completed_check_request.page_check_id,
            render_mode="published",
        )
    )
    persisted_script = db_session.get(ScriptRender, existing.script_render_id)
    assert persisted_script is not None
    persisted_script.execution_plan_id = completed_check_request.plan_id
    db_session.add(persisted_script)
    db_session.commit()

    response = client.post(
        f"/api/v1/check-requests/{completed_check_request.request_id}:publish",
        json={"schedule_expr": "0 */2 * * *"},
    )

    assert response.status_code == 201
    assert response.json()["script_render_id"] == str(existing.script_render_id)
    assert db_session.exec(select(ScriptRender)).all() == [persisted_script]
