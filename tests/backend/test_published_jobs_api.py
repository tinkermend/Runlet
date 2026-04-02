from __future__ import annotations

import anyio
from uuid import UUID

import pytest
from sqlmodel import select

from app.infrastructure.db.models.assets import ModulePlan, PageCheck
from app.infrastructure.db.models.execution import ScriptRender
from app.infrastructure.db.models.jobs import JobRun, PublishedJob, QueuedJob


@pytest.fixture
def seeded_publishable_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
    module_plan = ModulePlan(
        page_asset_id=seeded_page_check.page_asset_id,
        check_code=seeded_page_check.check_code,
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {
                "module": "nav.menu_chain",
                "params": {"menu_chain": ["系统管理", "用户管理"], "route_path": "/users"},
            },
            {"module": "page.wait_ready", "params": {"route_path": "/users"}},
            {"module": "assert.table_visible", "params": {"route_path": "/users"}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    seeded_page_check.module_plan_id = module_plan.id
    db_session.add(seeded_page_check)
    db_session.commit()
    db_session.refresh(seeded_page_check)
    return seeded_page_check


@pytest.fixture
def rendered_script(db_session, seeded_publishable_check) -> ScriptRender:
    from app.domains.runner_service.script_renderer import ScriptRenderer

    result = anyio.run(
        lambda: ScriptRenderer(session=db_session).render_page_check(
            page_check_id=seeded_publishable_check.id,
            render_mode="published",
        )
    )
    persisted = db_session.get(ScriptRender, result.script_render_id)
    assert persisted is not None
    return persisted


@pytest.fixture
def created_published_job(client, rendered_script):
    response = client.post(
        "/api/v1/published-jobs",
        json={
            "script_render_id": str(rendered_script.id),
            "page_check_id": str(rendered_script.render_metadata["page_check_id"]),
            "schedule_type": "cron",
            "schedule_expr": "0 */2 * * *",
            "trigger_source": "platform",
            "enabled": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_published_job_binds_script_and_asset_version(client, rendered_script, db_session):
    response = client.post(
        "/api/v1/published-jobs",
        json={
            "script_render_id": str(rendered_script.id),
            "page_check_id": str(rendered_script.render_metadata["page_check_id"]),
            "schedule_type": "cron",
            "schedule_expr": "0 */2 * * *",
            "trigger_source": "platform",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    published_job = db_session.get(PublishedJob, UUID(body["published_job_id"]))

    assert published_job is not None
    assert published_job.asset_version == rendered_script.render_metadata["asset_version"]
    assert published_job.state.value == "active"


def test_trigger_published_job_enqueues_run_check(client, created_published_job, db_session, rendered_script):
    response = client.post(f"/api/v1/published-jobs/{created_published_job['published_job_id']}:trigger")

    assert response.status_code == 202
    body = response.json()
    queued_job = db_session.get(QueuedJob, UUID(body["queued_job_id"]))
    job_run = db_session.get(JobRun, UUID(body["job_run_id"]))

    assert queued_job is not None
    assert queued_job.job_type == "run_check"
    assert queued_job.payload["published_job_id"] == created_published_job["published_job_id"]
    assert queued_job.payload["job_run_id"] == body["job_run_id"]
    assert queued_job.payload["queued_job_id"] == body["queued_job_id"]
    assert queued_job.payload["script_render_id"] == str(rendered_script.id)
    assert queued_job.payload["asset_version"] == rendered_script.render_metadata["asset_version"]
    assert queued_job.payload["runtime_policy"] == "published"
    assert queued_job.payload["schedule_expr"] == "0 */2 * * *"
    assert queued_job.payload["execution_track"] == "precompiled"
    assert queued_job.payload["trigger_source"] == "manual"
    assert queued_job.payload["scheduled_at"]
    assert job_run is not None
    assert job_run.published_job_id == UUID(created_published_job["published_job_id"])
    # Audit linkage should be queryable from JobRun without re-parsing QueuedJob payload.
    assert str(job_run.queued_job_id) == body["queued_job_id"]
    assert str(job_run.script_render_id) == str(rendered_script.id)
    assert job_run.asset_version == rendered_script.render_metadata["asset_version"]
    assert job_run.runtime_policy == "published"
    assert job_run.schedule_expr == "0 */2 * * *"


def test_get_published_job_runs_returns_created_runs(client, created_published_job):
    trigger_response = client.post(
        f"/api/v1/published-jobs/{created_published_job['published_job_id']}:trigger"
    )
    assert trigger_response.status_code == 202

    response = client.get(f"/api/v1/published-jobs/{created_published_job['published_job_id']}/runs")

    assert response.status_code == 200
    assert len(response.json()["runs"]) >= 1
