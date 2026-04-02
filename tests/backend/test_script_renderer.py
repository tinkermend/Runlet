import anyio
import pytest
from uuid import UUID

from app.infrastructure.db.models.assets import ModulePlan, PageCheck
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


def test_render_script_path_is_sanitized() -> None:
    from app.domains.runner_service.script_renderer import _build_script_path

    script_path = _build_script_path(
        asset_key="erp.users/../../unsafe",
        check_code="open/create",
        render_mode="published",
    )

    assert script_path == "generated/erp_users_unsafe_open_create_published.py"


@pytest.fixture
def seeded_renderable_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
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
def seeded_regex_route_check(db_session, seeded_page_check, seeded_auth_state) -> PageCheck:
    module_plan = ModulePlan(
        page_asset_id=seeded_page_check.page_asset_id,
        check_code="page_open",
        plan_version="v1",
        steps_json=[
            {"module": "auth.inject_state", "params": {"policy": "server_injected"}},
            {"module": "page.wait_ready", "params": {"route_path": "/users/[detail]"}},
            {"module": "assert.page_open", "params": {"route_path": "/users/[detail]"}},
        ],
    )
    db_session.add(module_plan)
    db_session.flush()

    seeded_page_check.check_code = "page_open"
    seeded_page_check.goal = "page_open"
    seeded_page_check.module_plan_id = module_plan.id
    db_session.add(seeded_page_check)
    db_session.commit()
    db_session.refresh(seeded_page_check)
    return seeded_page_check


@pytest.fixture
def script_renderer(db_session):
    from app.domains.runner_service.script_renderer import ScriptRenderer

    return ScriptRenderer(session=db_session)


@pytest.fixture
def rendered_script_text(script_renderer, seeded_renderable_check) -> str:
    result = anyio.run(
        lambda: script_renderer.render_page_check(
            page_check_id=seeded_renderable_check.id,
            render_mode="published",
        )
    )
    return result.script_text


@pytest.mark.anyio
async def test_render_script_for_page_check_persists_render_record(
    script_renderer,
    seeded_renderable_check,
    db_session,
):
    result = await script_renderer.render_page_check(
        page_check_id=seeded_renderable_check.id,
        render_mode="published",
    )

    persisted = db_session.get(ScriptRender, result.script_render_id)

    assert result.script_render_id is not None
    assert result.script_path.endswith(".py")
    assert persisted is not None
    assert persisted.render_mode == "published"
    assert persisted.render_result.value == "success"
    assert persisted.render_metadata["module_plan_id"] == str(seeded_renderable_check.module_plan_id)
    assert persisted.render_metadata["asset_version"] is not None
    assert persisted.render_metadata["auth_policy"] == "server_injected"
    assert persisted.render_metadata["runtime_policy"] == "published"
    assert persisted.render_metadata["script_sha256"]


def test_rendered_script_contains_expected_modules(rendered_script_text: str):
    assert "auth.inject_state" not in rendered_script_text
    assert "browser.new_context" in rendered_script_text
    assert "storage_state_path" not in rendered_script_text


@pytest.mark.anyio
async def test_rendered_script_escapes_route_path_for_regex(
    script_renderer,
    seeded_regex_route_check,
):
    result = await script_renderer.render_page_check(
        page_check_id=seeded_regex_route_check.id,
        render_mode="runtime",
    )

    assert r"\\[detail\\]" in result.script_text


def test_render_script_endpoint_returns_created_record(client, seeded_renderable_check, db_session):
    response = client.post(
        f"/api/v1/page-checks/{seeded_renderable_check.id}:render-script",
        json={"render_mode": "published"},
    )

    assert response.status_code == 201
    body = response.json()
    persisted = db_session.get(ScriptRender, UUID(body["script_render_id"]))

    assert persisted is not None
    assert body["page_check_id"] == str(seeded_renderable_check.id)
    assert body["render_mode"] == "published"
