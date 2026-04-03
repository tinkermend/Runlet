from app.infrastructure.db.models.execution import (
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionRun,
)
from app.shared.enums import ExecutionResultStatus


def test_get_check_request_result_returns_summary_and_artifacts(
    client,
    db_session,
    seeded_system,
    seeded_page_asset,
    seeded_page_check,
):
    request = ExecutionRequest(
        request_source="api",
        system_hint="ERP",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
    )
    db_session.add(request)
    db_session.flush()

    plan = ExecutionPlan(
        execution_request_id=request.id,
        resolved_system_id=seeded_system.id,
        resolved_page_asset_id=seeded_page_asset.id,
        resolved_page_check_id=seeded_page_check.id,
        execution_track="realtime",
        auth_policy="server_injected",
        module_plan_id=seeded_page_check.module_plan_id,
    )
    db_session.add(plan)
    db_session.flush()

    execution_run = ExecutionRun(
        execution_plan_id=plan.id,
        status="passed",
        duration_ms=1234,
        auth_status="reused",
        failure_category=None,
        asset_version=seeded_page_asset.asset_version,
    )
    db_session.add(execution_run)
    db_session.flush()

    execution_artifact = ExecutionArtifact(
        execution_run_id=execution_run.id,
        artifact_kind="module_execution",
        result_status=ExecutionResultStatus.SUCCESS,
        payload={
            "final_url": "https://erp.example.com/users",
            "page_title": "用户管理",
        },
    )
    screenshot_artifact = ExecutionArtifact(
        execution_run_id=execution_run.id,
        artifact_kind="screenshot",
        result_status=ExecutionResultStatus.SUCCESS,
        artifact_uri="/tmp/fake.png",
        payload={"mime_type": "image/png"},
    )
    db_session.add(execution_artifact)
    db_session.add(screenshot_artifact)
    db_session.commit()

    response = client.get(f"/api/v1/check-requests/{request.id}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == str(request.id)
    assert body["plan_id"] == str(plan.id)
    assert body["page_check_id"] == str(seeded_page_check.id)
    assert body["execution_track"] == "realtime_probe"
    assert body["needs_recrawl"] is False
    assert body["needs_recompile"] is False

    summary = body["execution_summary"]
    assert summary["execution_run_id"] == str(execution_run.id)
    assert summary["status"] == "passed"
    assert summary["auth_status"] == "reused"
    assert summary["duration_ms"] == 1234
    assert summary["failure_category"] is None
    assert summary["asset_version"] == seeded_page_asset.asset_version
    assert summary["final_url"] == "https://erp.example.com/users"
    assert summary["page_title"] == "用户管理"

    artifact_kinds = {artifact["artifact_kind"] for artifact in body["artifacts"]}
    assert artifact_kinds == {"module_execution", "screenshot"}
    assert {artifact["result_status"] for artifact in body["artifacts"]} == {"success"}


def test_get_check_request_result_returns_404_for_missing_request(client):
    response = client.get("/api/v1/check-requests/00000000-0000-0000-0000-000000000001/result")

    assert response.status_code == 404
