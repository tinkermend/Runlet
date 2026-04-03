# AI Playwright Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the new project's backend MVP foundation so a fresh repository can accept structured check requests, persist core platform entities, expose the first control-plane APIs, and enqueue auth/crawl/compile/check jobs with test coverage.

**Architecture:** Start with an API-first backend skeleton under `backend/`, backed by PostgreSQL and Redis. Implement the minimum fact-layer, asset-layer, execution-layer, and job-acceptance control-plane services needed for a working end-to-end control path, while leaving actual auth/crawl/runner deep execution to follow-on plans.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.x / SQLModel, PostgreSQL, Redis, APScheduler, pytest, httpx, Typer

---

## Scope Split

This spec package is too large for one safe implementation plan. Break delivery into four plans:

1. **This plan:** backend foundation, core data model, control-plane APIs, job acceptance
2. **Follow-on plan:** auth refresh service + crawl snapshot ingestion
3. **Follow-on plan:** asset compiler + drift classification
4. **Follow-on plan:** runner execution + script rendering + published job scheduling

This plan must still ship working, testable software on its own: a new repo with a bootable backend, migrations, persisted core models, and API endpoints matching the first contract set.

---

## File Structure

**Repository root to create:**
- `backend/pyproject.toml` - Python project metadata and dependencies for backend service
- `backend/README.md` - Backend setup and local run instructions
- `backend/.env.example` - Environment variable template for DB, Redis, app settings
- `backend/alembic.ini` - Alembic config
- `backend/alembic/env.py` - Migration environment
- `backend/alembic/versions/0001_initial_platform_schema.py` - Initial schema migration

**Backend application files to create:**
- `backend/src/app/main.py` - FastAPI app factory and router registration
- `backend/src/app/config/settings.py` - Pydantic settings
- `backend/src/app/shared/enums.py` - Shared status enums for assets, runs, jobs, auth
- `backend/src/app/shared/clock.py` - UTC time helpers
- `backend/src/app/api/deps.py` - DB/session dependencies
- `backend/src/app/api/router.py` - Top-level router
- `backend/src/app/api/endpoints/check_requests.py` - Check request and status APIs
- `backend/src/app/api/endpoints/page_checks.py` - Run page check and list checks APIs
- `backend/src/app/api/endpoints/auth.py` - Auth refresh submission API
- `backend/src/app/api/endpoints/crawl.py` - Crawl trigger API
- `backend/src/app/api/endpoints/assets.py` - Compile-assets trigger API
- `backend/src/app/infrastructure/db/base.py` - SQLModel metadata registry
- `backend/src/app/infrastructure/db/session.py` - Engine and async session factory
- `backend/src/app/infrastructure/db/models/systems.py` - `System`, `SystemCredential`, `AuthState`
- `backend/src/app/infrastructure/db/models/crawl.py` - `CrawlSnapshot`, `MenuNode`, `Page`, `PageElement`
- `backend/src/app/infrastructure/db/models/assets.py` - `PageAsset`, `PageCheck`, `ActionModule`, `ModulePlan`, `AssetSnapshot`, `IntentAlias`, `RuntimePolicy`
- `backend/src/app/infrastructure/db/models/execution.py` - `ExecutionRequest`, `ExecutionPlan`, `ExecutionRun`, `ExecutionArtifact`
- `backend/src/app/infrastructure/db/models/jobs.py` - `QueuedJob` and MVP job persistence primitives
- `backend/src/app/infrastructure/queue/dispatcher.py` - Job dispatcher abstraction with Redis-backed enqueue interface
- `backend/src/app/domains/control_plane/schemas.py` - Request/response DTOs matching API contracts
- `backend/src/app/domains/control_plane/repository.py` - Queries for systems/assets/checks/job records
- `backend/src/app/domains/control_plane/service.py` - Request normalization, plan creation, job submission
- `backend/src/app/domains/control_plane/job_types.py` - Accepted job type constants and payload helpers

**CLI bootstrap files to create:**
- `cli/pyproject.toml` - CLI package metadata
- `cli/src/openweb_cli/main.py` - Typer entrypoint for health and trigger commands

**Tests to create:**
- `tests/backend/test_boot.py` - App boot and health endpoint smoke test
- `tests/backend/conftest.py` - Test app, DB session, overrides
- `tests/backend/test_check_requests_api.py` - Check request creation and status retrieval
- `tests/backend/test_page_checks_api.py` - Direct page-check execution submission and listing
- `tests/backend/test_job_submission_api.py` - Auth refresh / crawl / compile trigger APIs
- `tests/backend/test_control_plane_service.py` - Service-level normalization and plan creation
- `tests/backend/test_initial_schema.py` - Migration smoke test for core tables and enums

**Docs to modify:**
- `CHANGELOG.md` - Add plan-writing summary

---

## Task 1: Scaffold the New Backend and CLI Packages

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/README.md`
- Create: `backend/.env.example`
- Create: `backend/src/app/main.py`
- Create: `backend/src/app/config/settings.py`
- Create: `backend/src/app/api/router.py`
- Create: `cli/pyproject.toml`
- Create: `cli/src/openweb_cli/main.py`

- [ ] **Step 1: Write the failing backend boot test**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_app_boots_with_health_router():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest ../tests/backend/test_boot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create backend package metadata and app skeleton**

```toml
[project]
name = "ai-playwright-platform-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic-settings>=2.3",
  "sqlmodel>=0.0.22",
  "asyncpg>=0.29",
  "redis>=5.0",
  "alembic>=1.13",
]
```

```python
from fastapi import FastAPI

from app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Playwright Platform")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api/v1")
    return app
```

- [ ] **Step 4: Add CLI skeleton**

```python
import typer

app = typer.Typer()


@app.command("doctor")
def doctor() -> None:
    typer.echo("ok")


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: Run tests to verify the app now boots**

Run: `cd backend && uv run pytest ../tests/backend/test_boot.py -v`
Expected: PASS

- [ ] **Step 6: Commit scaffold**

```bash
git add backend/pyproject.toml backend/README.md backend/.env.example backend/src/app/main.py backend/src/app/config/settings.py backend/src/app/api/router.py cli/pyproject.toml cli/src/openweb_cli/main.py tests/backend/test_boot.py
git commit -m "feat: scaffold ai playwright platform backend and cli"
```

---

## Task 2: Add Database Infrastructure and Initial Schema Models

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_initial_platform_schema.py`
- Create: `backend/src/app/infrastructure/db/base.py`
- Create: `backend/src/app/infrastructure/db/session.py`
- Create: `backend/src/app/shared/enums.py`
- Create: `backend/src/app/infrastructure/db/models/systems.py`
- Create: `backend/src/app/infrastructure/db/models/crawl.py`
- Create: `backend/src/app/infrastructure/db/models/assets.py`
- Create: `backend/src/app/infrastructure/db/models/execution.py`
- Create: `backend/src/app/infrastructure/db/models/jobs.py`
- Test: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: Write the failing schema smoke test**

```python
from sqlalchemy import inspect


def test_initial_schema_exposes_core_tables(db_engine):
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())
    assert {"systems", "page_assets", "page_checks", "execution_requests", "queued_jobs"} <= table_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest ../tests/backend/test_initial_schema.py -v`
Expected: FAIL because migrations and models do not exist

- [ ] **Step 3: Define shared enums and SQLModel metadata registry**

```python
from enum import StrEnum


class AssetStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    SUSPECT = "suspect"
    STALE = "stale"
    DISABLED = "disabled"
```

```python
from sqlmodel import SQLModel


class BaseModel(SQLModel):
    pass
```

- [ ] **Step 4: Implement the minimum core models**

```python
class System(SQLModel, table=True):
    __tablename__ = "systems"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=255)
    base_url: str = Field(max_length=512)
    framework_type: str = Field(max_length=32)
```

```python
class PageAsset(SQLModel, table=True):
    __tablename__ = "page_assets"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    page_id: UUID = Field(foreign_key="pages.id", index=True)
    asset_key: str = Field(index=True, max_length=255)
    asset_version: str = Field(max_length=64)
    status: AssetStatus = Field(default=AssetStatus.DRAFT)
```

```python
class ExecutionRequest(SQLModel, table=True):
    __tablename__ = "execution_requests"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    request_source: str = Field(max_length=32)
    system_hint: str = Field(max_length=255)
    page_hint: str | None = Field(default=None, max_length=255)
    check_goal: str = Field(max_length=64)
```

```python
class QueuedJob(SQLModel, table=True):
    __tablename__ = "queued_jobs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_type: str = Field(index=True, max_length=64)
    payload: dict = Field(sa_column=Column(JSONB, nullable=False))
    status: str = Field(default="accepted", max_length=32)
```

- [ ] **Step 5: Create initial Alembic migration for the MVP tables**

Include tables for:

- `systems`
- `system_credentials`
- `auth_states`
- `crawl_snapshots`
- `pages`
- `page_assets`
- `page_checks`
- `intent_aliases`
- `execution_requests`
- `execution_plans`
- `execution_runs`
- `queued_jobs`

Do **not** add `script_renders`, `published_jobs`, or `job_runs` in this plan; those belong to the runner/script/schedule follow-on plan.

- [ ] **Step 6: Run schema tests and migration smoke tests**

Run: `cd backend && uv run pytest ../tests/backend/test_initial_schema.py -v`
Expected: PASS

- [ ] **Step 7: Commit schema baseline**

```bash
git add backend/alembic.ini backend/alembic backend/src/app/shared/enums.py backend/src/app/infrastructure/db backend/src/app/infrastructure/db/models tests/backend/test_initial_schema.py
git commit -m "feat: add initial platform schema and db infrastructure"
```

---

## Task 3: Add Control-Plane DTOs, Repository, and Job Dispatcher Abstractions

**Files:**
- Create: `backend/src/app/domains/control_plane/schemas.py`
- Create: `backend/src/app/domains/control_plane/repository.py`
- Create: `backend/src/app/domains/control_plane/service.py`
- Create: `backend/src/app/domains/control_plane/job_types.py`
- Create: `backend/src/app/infrastructure/queue/dispatcher.py`
- Test: `tests/backend/test_control_plane_service.py`

- [ ] **Step 1: Write failing service tests for request normalization and job creation**

```python
async def test_submit_check_request_creates_request_plan_and_job(control_plane_service, seeded_asset):
    result = await control_plane_service.submit_check_request(
        system_hint="ERP",
        page_hint="用户管理",
        check_goal="table_render",
        strictness="balanced",
        time_budget_ms=20_000,
        request_source="skill",
    )
    assert result.execution_track == "precompiled"
    assert result.page_check_id is not None
    assert result.job_id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest ../tests/backend/test_control_plane_service.py -v`
Expected: FAIL because service and repository do not exist

- [ ] **Step 3: Define DTOs that match the API contract**

```python
class CreateCheckRequest(BaseModel):
    system_hint: str
    page_hint: str | None = None
    check_goal: str
    strictness: str = "balanced"
    time_budget_ms: int = 20_000
    request_source: str = "api"
```

```python
class CheckRequestAccepted(BaseModel):
    request_id: UUID
    plan_id: UUID
    page_check_id: UUID | None
    execution_track: str
    auth_policy: str
    job_id: UUID
    status: str = "accepted"
```

- [ ] **Step 4: Implement repository helpers and dispatcher abstraction**

```python
class QueueDispatcher(Protocol):
    async def enqueue(self, *, job_type: str, payload: dict[str, Any]) -> UUID: ...
```

```python
class SqlQueueDispatcher:
    async def enqueue(self, *, job_type: str, payload: dict[str, Any]) -> UUID:
        job = QueuedJob(job_type=job_type, payload=payload)
        self.session.add(job)
        await self.session.commit()
        return job.id
```

- [ ] **Step 5: Implement the minimal control-plane service**

Service behavior:

- resolve `system_hint`
- resolve `page_asset` / `page_check` when available
- decide `precompiled` vs `realtime`
- create `execution_request`
- create `execution_plan`
- enqueue a `run_check` job

- [ ] **Step 6: Run service tests**

Run: `cd backend && uv run pytest ../tests/backend/test_control_plane_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit control-plane service baseline**

```bash
git add backend/src/app/domains/control_plane backend/src/app/infrastructure/queue/dispatcher.py tests/backend/test_control_plane_service.py
git commit -m "feat: add control-plane service and queue abstraction"
```

---

## Task 4: Expose Check Request APIs

**Files:**
- Create: `backend/src/app/api/deps.py`
- Create: `backend/src/app/api/endpoints/check_requests.py`
- Modify: `backend/src/app/api/router.py`
- Test: `tests/backend/test_check_requests_api.py`

- [ ] **Step 1: Write failing API tests for create and get**

```python
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
```

```python
def test_get_check_request_returns_status(client, accepted_request):
    response = client.get(f"/api/v1/check-requests/{accepted_request.request_id}")
    assert response.status_code == 200
    assert response.json()["request_id"] == str(accepted_request.request_id)
```

- [ ] **Step 2: Run API tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_check_requests_api.py -v`
Expected: FAIL with 404 routes or import errors

- [ ] **Step 3: Implement request handlers**

```python
router = APIRouter(prefix="/check-requests", tags=["check-requests"])


@router.post("", status_code=202, response_model=CheckRequestAccepted)
async def create_check_request(payload: CreateCheckRequest, service: ControlPlaneServiceDep):
    return await service.submit_check_request(**payload.model_dump())
```

```python
@router.get("/{request_id}", response_model=CheckRequestStatus)
async def get_check_request(request_id: UUID, service: ControlPlaneServiceDep):
    return await service.get_check_request_status(request_id)
```

- [ ] **Step 4: Run API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_check_requests_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit check request APIs**

```bash
git add backend/src/app/api/deps.py backend/src/app/api/endpoints/check_requests.py backend/src/app/api/router.py tests/backend/test_check_requests_api.py
git commit -m "feat: add check request control-plane api"
```

---

## Task 5: Expose Page-Check and Asset Listing APIs

**Files:**
- Create: `backend/src/app/api/endpoints/page_checks.py`
- Modify: `backend/src/app/api/router.py`
- Test: `tests/backend/test_page_checks_api.py`

- [ ] **Step 1: Write failing tests for direct run and list checks**

```python
def test_post_page_check_run_accepts_job(client, seeded_page_check):
    response = client.post(
        f"/api/v1/page-checks/{seeded_page_check.id}:run",
        json={"strictness": "strict", "time_budget_ms": 15000, "triggered_by": "manual"},
    )
    assert response.status_code == 202
    assert response.json()["page_check_id"] == str(seeded_page_check.id)
```

```python
def test_get_page_asset_checks_lists_ready_checks(client, seeded_page_asset):
    response = client.get(f"/api/v1/page-assets/{seeded_page_asset.id}/checks")
    assert response.status_code == 200
    assert response.json()["checks"][0]["status"] == "ready"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_page_checks_api.py -v`
Expected: FAIL because routes do not exist

- [ ] **Step 3: Implement page-check handlers**

Expose:

- `POST /api/v1/page-checks/{page_check_id}:run`
- `GET /api/v1/page-assets/{page_asset_id}/checks`

Both must use the same control-plane service and repository layer.

- [ ] **Step 4: Run page-check API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_page_checks_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit page-check APIs**

```bash
git add backend/src/app/api/endpoints/page_checks.py backend/src/app/api/router.py tests/backend/test_page_checks_api.py
git commit -m "feat: add page-check run and asset listing api"
```

---

## Task 6: Expose Auth Refresh, Crawl Trigger, and Compile Trigger APIs

**Files:**
- Create: `backend/src/app/api/endpoints/auth.py`
- Create: `backend/src/app/api/endpoints/crawl.py`
- Create: `backend/src/app/api/endpoints/assets.py`
- Modify: `backend/src/app/api/router.py`
- Test: `tests/backend/test_job_submission_api.py`

- [ ] **Step 1: Write failing API tests for operational job submission**

```python
def test_post_auth_refresh_accepts_job(client, seeded_system):
    response = client.post(f"/api/v1/systems/{seeded_system.id}/auth:refresh")
    assert response.status_code == 202
    assert response.json()["job_type"] == "auth_refresh"
```

```python
def test_post_crawl_accepts_job(client, seeded_system):
    response = client.post(
        f"/api/v1/systems/{seeded_system.id}/crawl",
        json={"crawl_scope": "full", "framework_hint": "auto", "max_pages": 50},
    )
    assert response.status_code == 202
```

```python
def test_post_compile_assets_accepts_job(client, seeded_snapshot):
    response = client.post(
        f"/api/v1/snapshots/{seeded_snapshot.id}/compile-assets",
        json={"compile_scope": "impacted_pages_only"},
    )
    assert response.status_code == 202
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_job_submission_api.py -v`
Expected: FAIL because routes do not exist

- [ ] **Step 3: Implement the three trigger handlers**

Each handler should:

- validate the target entity exists
- enqueue the corresponding job (`auth_refresh`, `crawl`, `asset_compile`)
- return `202 Accepted`

- [ ] **Step 4: Run job-submission API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_job_submission_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit operational trigger APIs**

```bash
git add backend/src/app/api/endpoints/auth.py backend/src/app/api/endpoints/crawl.py backend/src/app/api/endpoints/assets.py backend/src/app/api/router.py tests/backend/test_job_submission_api.py
git commit -m "feat: add auth crawl and compile trigger apis"
```

---

## Task 7: Add Test Fixtures, Seed Helpers, and README Guidance

**Files:**
- Create: `tests/backend/conftest.py`
- Modify: `backend/README.md`
- Modify: `backend/.env.example`

- [ ] **Step 1: Write the failing fixture smoke test**

```python
def test_seed_helpers_create_minimum_precompiled_asset(seeded_page_check):
    assert seeded_page_check.check_code == "table_render"
```

- [ ] **Step 2: Run test to verify the fixture layer is incomplete**

Run: `cd backend && uv run pytest ../tests/backend -v -k seed_helpers`
Expected: FAIL because fixtures are not defined

- [ ] **Step 3: Implement reusable test fixtures**

Add fixtures for:

- test app and DB session
- seeded system
- seeded page asset
- seeded page check
- seeded snapshot
- accepted request

- [ ] **Step 4: Document local dev bootstrap**

Document:

- install commands
- env vars
- running migrations
- starting API
- running tests

- [ ] **Step 5: Run the backend test suite**

Run: `cd backend && uv run pytest ../tests/backend -v`
Expected: PASS

- [ ] **Step 6: Commit fixture and docs updates**

```bash
git add tests/backend/conftest.py backend/README.md backend/.env.example
git commit -m "test: add backend fixtures and local bootstrap docs"
```

---

## Task 8: Update Changelog and Capture Follow-On Planning Boundaries

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-04-01-ai-playwright-execution-platform-design.md`

- [ ] **Step 1: Add a changelog entry for the new-project foundation plan**

Add bullets summarizing:

- new backend MVP foundation plan
- core schema + control-plane API baseline
- follow-on plan boundaries for auth/crawler/compiler/runner

- [ ] **Step 2: Note follow-on implementation plans in the overview spec**

Add a short note under implementation order referencing:

- auth/crawler plan
- asset compiler plan
- runner/script/schedule plan

- [ ] **Step 3: Run a final docs-only verification**

Run: `git diff -- docs/superpowers/plans/2026-04-01-ai-playwright-platform-foundation.md CHANGELOG.md`
Expected: Only the expected planning/doc changes appear

- [ ] **Step 4: Commit planning docs updates**

```bash
git add docs/superpowers/plans/2026-04-01-ai-playwright-platform-foundation.md CHANGELOG.md docs/superpowers/specs/2026-04-01-ai-playwright-execution-platform-design.md
git commit -m "docs: add ai playwright platform foundation plan"
```

---

## Done Criteria

This plan is complete when the new repository can:

- boot the backend app locally
- apply the initial migration
- persist the core system / asset / execution / queued job tables
- accept and query structured check requests
- list page checks under a page asset
- accept auth refresh, crawl, and asset compile triggers
- pass the backend MVP test suite

At that point, the repo is ready for the next plan that implements real auth refresh and crawl execution.
