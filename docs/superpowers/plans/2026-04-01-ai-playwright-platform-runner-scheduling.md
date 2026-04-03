# AI Playwright Platform Runner, Script Render, and Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic page-check execution, Playwright script rendering, published job creation, and scheduler-driven execution so the platform can run checks itself and also emit runnable scripts for external schedulers.

**Architecture:** Build a `runner_service` that executes `module_plans` in a server-injected Playwright context, a `script renderer` that derives stable Playwright scripts from `page_checks`, and a scheduling layer that stores `published_jobs`, triggers them by cron/manual/event, and links job runs to execution runs.

**Tech Stack:** FastAPI, SQLModel, PostgreSQL, Redis, Playwright Python, APScheduler, pytest

---

## File Structure

**Files to Create:**
- `backend/src/app/domains/runner_service/schemas.py`
- `backend/src/app/domains/runner_service/service.py`
- `backend/src/app/domains/runner_service/module_executor.py`
- `backend/src/app/domains/runner_service/script_renderer.py`
- `backend/src/app/domains/runner_service/scheduler.py`
- `backend/src/app/jobs/run_check_job.py`
- `backend/src/app/jobs/published_job_trigger.py`

**Files to Modify:**
- `backend/src/app/shared/enums.py`
- `backend/src/app/infrastructure/db/models/execution.py`
- `backend/src/app/infrastructure/db/models/jobs.py`
- `backend/src/app/api/endpoints/check_requests.py`
- `backend/src/app/api/endpoints/page_checks.py`
- `backend/src/app/api/endpoints/assets.py`
- `backend/src/app/workers/runner.py`
- `backend/alembic/versions/0004_runner_and_scheduling.py`
- `backend/README.md`

**Tests to Create:**
- `tests/backend/test_runner_service.py`
- `tests/backend/test_script_renderer.py`
- `tests/backend/test_run_check_job.py`
- `tests/backend/test_published_jobs_api.py`
- `tests/backend/test_scheduler_service.py`

**Docs to Modify:**
- `CHANGELOG.md`

---

## Task 1: Extend Schema for Execution Artifacts, Script Renders, and Published Jobs

**Files:**
- Modify: `backend/src/app/shared/enums.py`
- Modify: `backend/src/app/infrastructure/db/models/execution.py`
- Modify: `backend/src/app/infrastructure/db/models/jobs.py`
- Create: `backend/alembic/versions/0004_runner_and_scheduling.py`
- Test: `tests/backend/test_script_renderer.py`

- [ ] **Step 1: Write failing schema tests for script and scheduling entities**

```python
def test_runner_schema_exposes_script_and_job_models():
    assert hasattr(ScriptRender, "render_mode")
    assert hasattr(PublishedJob, "schedule_expr")
    assert hasattr(JobRun, "execution_run_id")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_script_renderer.py -v -k schema_models`
Expected: FAIL because runner/scheduling models are missing

- [ ] **Step 3: Add execution and scheduling models**

Add:

- `ExecutionArtifact`
- `ScriptRender`
- `PublishedJob`
- `JobRun`

with status enums for:

- execution result
- render result
- published job state

- [ ] **Step 4: Create migration `0004_runner_and_scheduling.py`**

- [ ] **Step 5: Run schema tests**

Run: `cd backend && uv run pytest ../tests/backend/test_script_renderer.py -v -k schema_models`
Expected: PASS

- [ ] **Step 6: Commit runner/scheduling schema**

```bash
git add backend/src/app/shared/enums.py backend/src/app/infrastructure/db/models/execution.py backend/src/app/infrastructure/db/models/jobs.py backend/alembic/versions/0004_runner_and_scheduling.py tests/backend/test_script_renderer.py
git commit -m "feat: add runner and scheduling schema"
```

---

## Task 2: Implement Module Executor and Runner Service

**Files:**
- Create: `backend/src/app/domains/runner_service/schemas.py`
- Create: `backend/src/app/domains/runner_service/module_executor.py`
- Create: `backend/src/app/domains/runner_service/service.py`
- Test: `tests/backend/test_runner_service.py`

- [ ] **Step 1: Write failing runner service tests**

```python
async def test_run_page_check_creates_execution_run_and_artifacts(runner_service, seeded_ready_check):
    result = await runner_service.run_page_check(page_check_id=seeded_ready_check.id)
    assert result.status in {"passed", "failed"}
    assert result.execution_run_id is not None
```

```python
async def test_run_page_check_uses_server_injected_auth(runner_service, seeded_ready_check):
    result = await runner_service.run_page_check(page_check_id=seeded_ready_check.id)
    assert result.auth_status in {"reused", "refreshed", "blocked"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_runner_service.py -v`
Expected: FAIL because runner service does not exist

- [ ] **Step 3: Implement deterministic module executor**

Support at least:

- `auth.inject_state`
- `nav.menu_chain`
- `page.wait_ready`
- `assert.table_visible`
- `assert.page_open`

The module executor must consume `module_plan.steps_json` and produce structured step results.

- [ ] **Step 4: Implement runner service orchestration**

The runner service must:

- resolve `page_check` and `module_plan`
- fetch a valid auth state
- inject auth into Playwright context
- execute the module plan
- persist `execution_runs` and `execution_artifacts`

- [ ] **Step 5: Run runner service tests**

Run: `cd backend && uv run pytest ../tests/backend/test_runner_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit runner service**

```bash
git add backend/src/app/domains/runner_service tests/backend/test_runner_service.py
git commit -m "feat: add runner service and module executor"
```

---

## Task 3: Implement Run-Check Job Flow

**Files:**
- Create: `backend/src/app/jobs/run_check_job.py`
- Modify: `backend/src/app/workers/runner.py`
- Test: `tests/backend/test_run_check_job.py`

- [ ] **Step 1: Write failing run-check job tests**

```python
async def test_run_check_job_creates_execution_run(job_runner, queued_run_check_job):
    await job_runner.run_once()
    refreshed = await load_job(queued_run_check_job.id)
    assert refreshed.status == "completed"
    execution_run = await load_latest_execution_run()
    assert execution_run is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_run_check_job.py -v`
Expected: FAIL because `run_check` handler does not exist

- [ ] **Step 3: Implement run-check job handler**

The handler must:

- call `RunnerService.run_page_check`
- update queue status
- persist failure details

- [ ] **Step 4: Register `run_check` in worker dispatch**

- [ ] **Step 5: Run run-check job tests**

Run: `cd backend && uv run pytest ../tests/backend/test_run_check_job.py -v`
Expected: PASS

- [ ] **Step 6: Commit run-check job flow**

```bash
git add backend/src/app/jobs/run_check_job.py backend/src/app/workers/runner.py tests/backend/test_run_check_job.py
git commit -m "feat: add run-check worker flow"
```

---

## Task 4: Implement Script Renderer

**Files:**
- Create: `backend/src/app/domains/runner_service/script_renderer.py`
- Modify: `backend/src/app/api/endpoints/page_checks.py`
- Test: `tests/backend/test_script_renderer.py`

- [ ] **Step 1: Write failing script-renderer tests**

```python
async def test_render_script_for_page_check_persists_render_record(script_renderer, seeded_ready_check):
    result = await script_renderer.render_page_check(page_check_id=seeded_ready_check.id, render_mode="published")
    assert result.script_render_id is not None
    assert result.script_path.endswith(".py")
```

```python
def test_rendered_script_contains_expected_modules(rendered_script_text):
    assert "auth.inject_state" not in rendered_script_text
    assert "browser.new_context" in rendered_script_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_script_renderer.py -v`
Expected: FAIL because script renderer does not exist

- [ ] **Step 3: Implement script renderer**

Renderer requirements:

- accept `page_check_id`
- resolve `module_plan`
- render deterministic Playwright Python script
- persist a `script_renders` record
- support `runtime` and `published` modes

- [ ] **Step 4: Add render endpoint**

Expose:

- `POST /api/v1/page-checks/{page_check_id}:render-script`

- [ ] **Step 5: Run script-renderer tests**

Run: `cd backend && uv run pytest ../tests/backend/test_script_renderer.py -v`
Expected: PASS

- [ ] **Step 6: Commit script renderer**

```bash
git add backend/src/app/domains/runner_service/script_renderer.py backend/src/app/api/endpoints/page_checks.py tests/backend/test_script_renderer.py
git commit -m "feat: add playwright script renderer"
```

---

## Task 5: Implement Published Jobs API and Scheduler Service

**Files:**
- Create: `backend/src/app/domains/runner_service/scheduler.py`
- Create: `backend/src/app/jobs/published_job_trigger.py`
- Modify: `backend/src/app/api/endpoints/assets.py`
- Modify: `backend/src/app/api/endpoints/page_checks.py`
- Test: `tests/backend/test_published_jobs_api.py`
- Test: `tests/backend/test_scheduler_service.py`

- [ ] **Step 1: Write failing scheduling tests**

```python
def test_create_published_job_binds_script_and_asset_version(client, rendered_script):
    response = client.post(
        "/api/v1/published-jobs",
        json={
            "script_render_id": str(rendered_script.id),
            "page_check_id": str(rendered_script.page_check_id),
            "schedule_type": "cron",
            "schedule_expr": "0 */2 * * *",
            "trigger_source": "platform",
            "enabled": True,
        },
    )
    assert response.status_code == 201
```

```python
async def test_scheduler_triggers_due_jobs(scheduler_service, seeded_published_job):
    triggered = await scheduler_service.trigger_due_jobs()
    assert triggered >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_published_jobs_api.py ../tests/backend/test_scheduler_service.py -v`
Expected: FAIL because APIs and scheduler do not exist

- [ ] **Step 3: Implement published jobs CRUD-lite and trigger endpoint**

Expose:

- `POST /api/v1/published-jobs`
- `POST /api/v1/published-jobs/{published_job_id}:trigger`
- `GET /api/v1/published-jobs/{published_job_id}/runs`

- [ ] **Step 4: Implement scheduler service**

Scheduler requirements:

- scan enabled cron jobs
- create `job_runs`
- enqueue `run_check` jobs
- link `job_runs` to later `execution_runs`

- [ ] **Step 5: Run scheduling tests**

Run: `cd backend && uv run pytest ../tests/backend/test_published_jobs_api.py ../tests/backend/test_scheduler_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit published jobs and scheduler**

```bash
git add backend/src/app/domains/runner_service/scheduler.py backend/src/app/jobs/published_job_trigger.py backend/src/app/api/endpoints/assets.py backend/src/app/api/endpoints/page_checks.py tests/backend/test_published_jobs_api.py tests/backend/test_scheduler_service.py
git commit -m "feat: add published jobs and scheduler service"
```

---

## Task 6: Document Execution and Scheduling Flow

**Files:**
- Modify: `backend/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document runner and scheduling usage**

Document:

- how `run_check` jobs flow through worker
- how to render scripts
- how to create `published_jobs`
- how cron/manual triggering works

- [ ] **Step 2: Run full runner/scheduling suite**

Run: `cd backend && uv run pytest ../tests/backend/test_runner_service.py ../tests/backend/test_run_check_job.py ../tests/backend/test_script_renderer.py ../tests/backend/test_published_jobs_api.py ../tests/backend/test_scheduler_service.py -v`
Expected: PASS

- [ ] **Step 3: Commit docs updates**

```bash
git add backend/README.md CHANGELOG.md
git commit -m "docs: document runner script render and scheduling flow"
```

---

## Done Criteria

This plan is complete when the new project can:

- execute a `page_check` through deterministic `module_plan` execution
- persist execution runs and artifacts
- render a `page_check` to a Playwright script
- create and trigger `published_jobs`
- schedule due jobs via cron scanning
- pass the runner and scheduling test suite

At that point, the platform has reached the intended MVP end-to-end capability for internal execution and external script publication.
