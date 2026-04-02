from app.infrastructure.db.models.execution import ExecutionArtifact, ScriptRender
from app.infrastructure.db.models.jobs import JobRun, PublishedJob


def test_schema_models_runner_exposes_script_and_job_models() -> None:
    assert hasattr(ExecutionArtifact, "artifact_kind")
    assert hasattr(ScriptRender, "render_mode")
    assert hasattr(PublishedJob, "schedule_expr")
    assert hasattr(JobRun, "execution_run_id")


def test_published_job_schema_enforces_identity_and_runtime_defaults() -> None:
    job_key_column = PublishedJob.__table__.c["job_key"]
    page_check_column = PublishedJob.__table__.c["page_check_id"]
    updated_at_column = PublishedJob.__table__.c["updated_at"]

    assert job_key_column.unique is True
    assert page_check_column.nullable is False
    assert updated_at_column.onupdate is not None
