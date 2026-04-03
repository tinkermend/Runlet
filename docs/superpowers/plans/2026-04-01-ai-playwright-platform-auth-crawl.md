# AI Playwright Platform Auth and Crawl Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first real runtime ingestion path for the new project: refresh system auth state, run a crawl job, persist crawl snapshots, and materialize menu/page/element facts for later asset compilation.

**Architecture:** Build an `auth_service` that owns credential loading, login-state refresh, validation, and state persistence, plus a `crawler_service` that consumes a valid auth state to produce `crawl_snapshots`, `menu_nodes`, `pages`, and `page_elements`. Keep asset compilation out of scope except for emitting a follow-up compile job when crawl succeeds.

**Tech Stack:** FastAPI, SQLModel, SQLAlchemy 2.x, PostgreSQL, Redis, Playwright Python, APScheduler, pytest

---

## File Structure

**Files to Create:**
- `backend/src/app/domains/auth_service/schemas.py` - Auth refresh command/result DTOs
- `backend/src/app/domains/auth_service/service.py` - Auth refresh orchestration and validation
- `backend/src/app/domains/auth_service/crypto.py` - Encryption/decryption wrapper for credentials
- `backend/src/app/domains/auth_service/browser_login.py` - Playwright login flow and storage state capture
- `backend/src/app/domains/crawler_service/schemas.py` - Crawl command/result DTOs
- `backend/src/app/domains/crawler_service/service.py` - Crawl orchestration and fact persistence
- `backend/src/app/domains/crawler_service/extractors/router_runtime.py` - Vue/React runtime route extraction
- `backend/src/app/domains/crawler_service/extractors/dom_menu.py` - DOM menu traversal fallback
- `backend/src/app/jobs/auth_refresh_job.py` - Worker entrypoint for auth refresh jobs
- `backend/src/app/jobs/crawl_job.py` - Worker entrypoint for crawl jobs
- `backend/src/app/workers/runner.py` - Minimal worker loop for queued auth/crawl jobs

**Files to Modify:**
- `backend/src/app/shared/enums.py` - Add auth and crawl job status enums
- `backend/src/app/infrastructure/db/models/systems.py` - Add encrypted credential and auth-state fields needed by runtime
- `backend/src/app/infrastructure/db/models/crawl.py` - Complete crawl snapshot/page/menu/element fields
- `backend/src/app/infrastructure/db/models/jobs.py` - Add worker-consumable queue status fields
- `backend/src/app/api/endpoints/auth.py` - Return accepted auth refresh jobs
- `backend/src/app/api/endpoints/crawl.py` - Return accepted crawl jobs
- `backend/alembic/versions/0002_auth_and_crawl_runtime.py` - Migration for auth/crawl fields
- `backend/README.md` - Local auth/crawl run instructions

**Tests to Create:**
- `tests/backend/test_auth_service.py`
- `tests/backend/test_auth_job.py`
- `tests/backend/test_crawler_service.py`
- `tests/backend/test_crawl_job.py`
- `tests/backend/test_worker_runner.py`

**Docs to Modify:**
- `CHANGELOG.md`

---

## Task 1: Extend Schema for Auth and Crawl Runtime

**Files:**
- Modify: `backend/src/app/shared/enums.py`
- Modify: `backend/src/app/infrastructure/db/models/systems.py`
- Modify: `backend/src/app/infrastructure/db/models/crawl.py`
- Modify: `backend/src/app/infrastructure/db/models/jobs.py`
- Create: `backend/alembic/versions/0002_auth_and_crawl_runtime.py`
- Test: `tests/backend/test_auth_service.py`

- [ ] **Step 1: Write the failing schema test for auth and crawl runtime fields**

```python
def test_auth_and_crawl_models_expose_runtime_fields():
    assert hasattr(SystemCredential, "login_auth_type")
    assert hasattr(AuthState, "storage_state")
    assert hasattr(CrawlSnapshot, "quality_score")
    assert hasattr(PageElement, "stability_score")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_service.py -v -k runtime_fields`
Expected: FAIL because the runtime fields or models are incomplete

- [ ] **Step 3: Add enums and model fields required by auth and crawl runtime**

Include:

- auth state status
- crawl job status
- `AuthState.storage_state`, `validated_at`, `expires_at`
- `CrawlSnapshot.quality_score`, `degraded`, `framework_detected`
- `MenuNode.playwright_locator`
- `Page.page_summary`
- `PageElement.playwright_locator`, `stability_score`, `usage_description`

- [ ] **Step 4: Add migration `0002_auth_and_crawl_runtime.py`**

The migration must add only fields needed for auth refresh and crawl persistence. Do not add asset compiler or published job tables in this migration.

- [ ] **Step 5: Run schema and migration tests**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_service.py -v -k runtime_fields`
Expected: PASS

- [ ] **Step 6: Commit schema runtime extension**

```bash
git add backend/src/app/shared/enums.py backend/src/app/infrastructure/db/models/systems.py backend/src/app/infrastructure/db/models/crawl.py backend/src/app/infrastructure/db/models/jobs.py backend/alembic/versions/0002_auth_and_crawl_runtime.py tests/backend/test_auth_service.py
git commit -m "feat: extend schema for auth and crawl runtime"
```

---

## Task 2: Implement Auth Refresh Domain

**Files:**
- Create: `backend/src/app/domains/auth_service/schemas.py`
- Create: `backend/src/app/domains/auth_service/service.py`
- Create: `backend/src/app/domains/auth_service/crypto.py`
- Create: `backend/src/app/domains/auth_service/browser_login.py`
- Test: `tests/backend/test_auth_service.py`

- [ ] **Step 1: Write failing auth refresh service tests**

```python
async def test_refresh_auth_state_persists_valid_state(auth_service, seeded_system_credentials):
    result = await auth_service.refresh_auth_state(system_id=seeded_system_credentials.system_id)
    assert result.status == "success"
    assert result.auth_state_id is not None
```

```python
async def test_refresh_auth_state_marks_failure_when_login_fails(auth_service, seeded_system_credentials):
    result = await auth_service.refresh_auth_state(system_id=seeded_system_credentials.system_id)
    assert result.status in {"failed", "retryable_failed"}
```

- [ ] **Step 2: Run auth service tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_service.py -v`
Expected: FAIL because auth service does not exist

- [ ] **Step 3: Implement credential decryption and auth refresh orchestration**

Auth service must:

- load encrypted credentials
- decrypt them
- call browser login adapter
- validate the captured state
- persist `auth_states`
- update system auth metadata

- [ ] **Step 4: Implement browser login adapter contract**

Start with a thin interface and fakeable Playwright implementation. The first implementation can support:

- login URL navigation
- username/password fill
- submit
- storage state capture

Keep captcha variants and advanced login challenges out of scope for this plan unless required to preserve API shape.

- [ ] **Step 5: Run auth service tests**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit auth refresh domain**

```bash
git add backend/src/app/domains/auth_service tests/backend/test_auth_service.py
git commit -m "feat: add auth refresh domain service"
```

---

## Task 3: Implement Auth Refresh Job and Worker Execution

**Files:**
- Create: `backend/src/app/jobs/auth_refresh_job.py`
- Create: `backend/src/app/workers/runner.py`
- Test: `tests/backend/test_auth_job.py`
- Test: `tests/backend/test_worker_runner.py`

- [ ] **Step 1: Write failing auth job tests**

```python
async def test_auth_refresh_job_marks_queue_item_completed(job_runner, queued_auth_job):
    await job_runner.run_once()
    refreshed = await load_job(queued_auth_job.id)
    assert refreshed.status == "completed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_job.py ../tests/backend/test_worker_runner.py -v`
Expected: FAIL because worker and job handlers do not exist

- [ ] **Step 3: Implement auth refresh job handler**

The handler must:

- load the queued job payload
- call `AuthService.refresh_auth_state`
- transition queue status to `running`, then `completed` or `failed`
- store failure details when refresh fails

- [ ] **Step 4: Implement minimal worker loop**

Worker behavior:

- fetch accepted queued jobs in FIFO order
- dispatch by `job_type`
- run one job safely
- update status and timestamps

- [ ] **Step 5: Run worker tests**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_job.py ../tests/backend/test_worker_runner.py -v`
Expected: PASS

- [ ] **Step 6: Commit auth worker support**

```bash
git add backend/src/app/jobs/auth_refresh_job.py backend/src/app/workers/runner.py tests/backend/test_auth_job.py tests/backend/test_worker_runner.py
git commit -m "feat: add auth refresh worker execution"
```

---

## Task 4: Implement Crawl Service and Fact Persistence

**Files:**
- Create: `backend/src/app/domains/crawler_service/schemas.py`
- Create: `backend/src/app/domains/crawler_service/service.py`
- Create: `backend/src/app/domains/crawler_service/extractors/router_runtime.py`
- Create: `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: Write failing crawl service tests**

```python
async def test_run_crawl_persists_snapshot_pages_and_elements(crawler_service, seeded_auth_state):
    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")
    assert result.status == "success"
    assert result.snapshot_id is not None
    assert result.pages_saved >= 1
```

```python
async def test_run_crawl_requires_valid_auth_state(crawler_service, seeded_system):
    result = await crawler_service.run_crawl(system_id=seeded_system.id, crawl_scope="full")
    assert result.status == "auth_required"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_crawler_service.py -v`
Expected: FAIL because crawler service does not exist

- [ ] **Step 3: Implement crawl service orchestration**

Crawl service must:

- load latest valid auth state
- open a browser context with storage state
- execute route extraction
- fall back to DOM menu traversal when runtime extraction misses
- persist snapshot/page/menu/element facts

- [ ] **Step 4: Implement extractor contracts with fakeable adapters**

Keep extractor modules independent and small:

- `router_runtime.py` returns route/page candidates
- `dom_menu.py` returns menu/page/element candidates

The first implementation can be thin and test-double friendly. Do not overbuild heuristics in this plan.

- [ ] **Step 5: Run crawler service tests**

Run: `cd backend && uv run pytest ../tests/backend/test_crawler_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit crawl service**

```bash
git add backend/src/app/domains/crawler_service tests/backend/test_crawler_service.py
git commit -m "feat: add crawl service and fact persistence"
```

---

## Task 5: Implement Crawl Job and Compile-Job Handoff

**Files:**
- Create: `backend/src/app/jobs/crawl_job.py`
- Modify: `backend/src/app/workers/runner.py`
- Test: `tests/backend/test_crawl_job.py`

- [ ] **Step 1: Write failing crawl job tests**

```python
async def test_crawl_job_persists_snapshot_and_enqueues_compile(job_runner, queued_crawl_job):
    await job_runner.run_once()
    refreshed_job = await load_job(queued_crawl_job.id)
    assert refreshed_job.status == "completed"
    compile_job = await load_latest_job(job_type="asset_compile")
    assert compile_job is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_crawl_job.py -v`
Expected: FAIL because crawl job handler does not exist

- [ ] **Step 3: Implement crawl job handler**

The handler must:

- call `CrawlerService.run_crawl`
- update queue state
- enqueue an `asset_compile` job with the new `snapshot_id` when crawl succeeds

- [ ] **Step 4: Extend worker dispatch table**

Register:

- `auth_refresh`
- `crawl`

Leave `asset_compile` as accepted-but-unhandled until the next plan; worker should mark unknown job types as blocked or skipped with a clear reason.

- [ ] **Step 5: Run crawl job tests**

Run: `cd backend && uv run pytest ../tests/backend/test_crawl_job.py -v`
Expected: PASS

- [ ] **Step 6: Commit crawl job flow**

```bash
git add backend/src/app/jobs/crawl_job.py backend/src/app/workers/runner.py tests/backend/test_crawl_job.py
git commit -m "feat: add crawl job flow and compile handoff"
```

---

## Task 6: Update API Surface and Docs for Real Auth/Crawl Runtime

**Files:**
- Modify: `backend/src/app/api/endpoints/auth.py`
- Modify: `backend/src/app/api/endpoints/crawl.py`
- Modify: `backend/README.md`
- Modify: `backend/.env.example`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing API-level smoke tests for auth/crawl acceptance payloads**

```python
def test_auth_refresh_returns_job_identifier(client, seeded_system):
    response = client.post(f"/api/v1/systems/{seeded_system.id}/auth:refresh")
    assert response.status_code == 202
    assert response.json()["job_id"]
```

```python
def test_crawl_returns_job_identifier(client, seeded_system):
    response = client.post(
        f"/api/v1/systems/{seeded_system.id}/crawl",
        json={"crawl_scope": "full", "framework_hint": "auto", "max_pages": 20},
    )
    assert response.status_code == 202
    assert response.json()["job_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_job_submission_api.py -v -k "job_identifier"`
Expected: FAIL because handlers do not return runtime queue metadata yet

- [ ] **Step 3: Update handlers and docs**

API docs and README must cover:

- required environment variables
- how to run worker
- how to trigger auth refresh
- how to trigger crawl
- how compile handoff works after crawl

- [ ] **Step 4: Run full auth/crawl-related test suite**

Run: `cd backend && uv run pytest ../tests/backend/test_auth_service.py ../tests/backend/test_auth_job.py ../tests/backend/test_crawler_service.py ../tests/backend/test_crawl_job.py ../tests/backend/test_worker_runner.py ../tests/backend/test_job_submission_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit API and docs updates**

```bash
git add backend/src/app/api/endpoints/auth.py backend/src/app/api/endpoints/crawl.py backend/README.md backend/.env.example CHANGELOG.md
git commit -m "docs: document auth and crawl runtime flow"
```

---

## Done Criteria

This plan is complete when the new project can:

- refresh and persist auth state through a real auth domain service
- execute auth refresh jobs through the worker
- run a crawl using a valid auth state
- persist crawl snapshots, pages, and elements
- enqueue a follow-up `asset_compile` job when crawl succeeds
- pass the auth/crawl test suite

At that point, the project is ready for the asset compiler and drift-governance plan.
