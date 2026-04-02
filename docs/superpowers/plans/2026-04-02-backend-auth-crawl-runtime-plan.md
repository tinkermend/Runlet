# Backend Auth Crawl Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first complete backend runtime loop for system-level auth refresh and crawl, including policy management, `control_plane`-owned scheduler/worker daemons, `ddddocr`-based captcha solving, and real crawl fact persistence.

**Architecture:** Keep all cross-domain orchestration inside `control_plane` runtime entrypoints. Add system-level auth/crawl policy models plus API management, then execute those policies through a scheduler daemon that only enqueues jobs and a worker daemon that only consumes jobs. Extend `auth_service` with captcha-aware login state transitions and extend `crawler_service` with real extractors that persist facts and return results for `control_plane` to hand off into `asset_compile`.

**Tech Stack:** FastAPI, SQLModel, SQLAlchemy 2.x, Alembic, PostgreSQL, Playwright Python, ddddocr, pytest, anyio

---

## File Structure

**Files to Create:**
- `backend/src/app/infrastructure/db/models/runtime_policies.py` - System-level auth and crawl policy tables
- `backend/src/app/api/endpoints/runtime_policies.py` - Policy management endpoints for auth/crawl schedules
- `backend/src/app/domains/control_plane/runtime_policies.py` - DTOs and service helpers for reading/updating runtime policies
- `backend/src/app/domains/control_plane/runtime_scheduler.py` - `control_plane` runtime scanner for auth/crawl policies
- `backend/src/app/runtime/worker_daemon.py` - Long-running worker loop entrypoint owned by `control_plane`
- `backend/src/app/runtime/scheduler_daemon.py` - Long-running scheduler loop entrypoint owned by `control_plane`
- `backend/src/app/domains/auth_service/captcha_solver.py` - Captcha abstraction and `ddddocr` implementation
- `tests/backend/test_runtime_policies_api.py` - API coverage for auth/crawl policy management
- `tests/backend/test_runtime_scheduler.py` - Scheduler scanner coverage for auth/crawl policies
- `tests/backend/test_runtime_daemons.py` - Worker/scheduler daemon loop coverage
- `tests/backend/test_captcha_solver.py` - `ddddocr` solver contract coverage

**Files to Modify:**
- `backend/src/app/infrastructure/db/models/systems.py` - Optional policy relationships and auth-state constraints
- `backend/src/app/infrastructure/db/models/jobs.py` - Add claim/audit fields or payload expectations for policy-triggered jobs
- `backend/src/app/infrastructure/db/models/crawl.py` - Add crawl failure/warning metadata
- `backend/src/app/shared/enums.py` - Add runtime policy state and failure enums if missing
- `backend/alembic/versions/0005_job_run_audit_linkage.py` or new migration after it - Add runtime policy schema and queue audit fields
- `backend/src/app/api/router.py` - Register runtime policy routes
- `backend/src/app/api/deps.py` - Wire policy services, scheduler, and daemon dependencies
- `backend/src/app/config/settings.py` - Add scheduler/worker polling config and `ddddocr` toggle
- `backend/src/app/domains/control_plane/service.py` - Add get/update runtime policy operations and policy-aware enqueue payloads
- `backend/src/app/domains/control_plane/repository.py` - Persist and query runtime policies
- `backend/src/app/domains/control_plane/schemas.py` - Add runtime policy DTOs
- `backend/src/app/domains/auth_service/browser_login.py` - Replace thin login flow with captcha-aware state machine
- `backend/src/app/domains/auth_service/service.py` - Inject solver, tighten auth-state persistence and output boundaries
- `backend/src/app/domains/auth_service/schemas.py` - Add captcha challenge/solution and richer auth error result types
- `backend/src/app/jobs/auth_refresh_job.py` - Persist policy-trigger metadata and clearer failure categories
- `backend/src/app/jobs/crawl_job.py` - Keep `asset_compile` handoff in `control_plane` runtime and persist crawl warnings/failure reason
- `backend/src/app/workers/runner.py` - Add safe claim/dispatch behavior for daemon usage
- `backend/src/app/domains/crawler_service/extractors/router_runtime.py` - Replace null extractor with real route extraction
- `backend/src/app/domains/crawler_service/extractors/dom_menu.py` - Replace null extractor with stable DOM traversal
- `backend/src/app/domains/crawler_service/service.py` - Persist degraded/failure metadata and consume real extractors
- `backend/src/app/main.py` - Optionally expose daemon health wiring only if needed by current app patterns
- `backend/README.md` - Document worker/scheduler runtime startup and policy configuration
- `docs/base_info.md` - Keep test-system caveats aligned if wording needs correction
- `docs/superpowers/specs/2026-04-02-backend-auth-crawl-runtime-design.md` - Commit reviewed spec fixes already approved
- `CHANGELOG.md` - Record plan and any final spec wording correction

**Files to Reuse for Tests:**
- `tests/backend/test_auth_service.py`
- `tests/backend/test_auth_job.py`
- `tests/backend/test_crawler_service.py`
- `tests/backend/test_crawl_job.py`
- `tests/backend/test_worker_runner.py`
- `tests/backend/test_job_submission_api.py`

---

## Task 1: Add Runtime Policy Schema and Migration

**Files:**
- Create: `backend/src/app/infrastructure/db/models/runtime_policies.py`
- Modify: `backend/src/app/infrastructure/db/models/systems.py`
- Modify: `backend/src/app/shared/enums.py`
- Create or Modify: `backend/alembic/versions/0006_runtime_policies_and_queue_claims.py`
- Test: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: Write the failing schema test**

```python
def test_runtime_policy_tables_exist(inspector):
    table_names = set(inspector.get_table_names())
    assert "system_auth_policies" in table_names
    assert "system_crawl_policies" in table_names
```

```python
def test_runtime_policy_models_expose_expected_fields():
    assert hasattr(SystemAuthPolicy, "auth_mode")
    assert hasattr(SystemAuthPolicy, "captcha_provider")
    assert hasattr(SystemCrawlPolicy, "crawl_scope")
    assert hasattr(SystemCrawlPolicy, "schedule_expr")
```

- [ ] **Step 2: Run the schema tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k runtime_policy`
Expected: FAIL because the runtime policy tables and models do not exist

- [ ] **Step 3: Add runtime policy models and enums**

```python
class SystemAuthPolicy(BaseModel, table=True):
    __tablename__ = "system_auth_policies"
    system_id: UUID = Field(foreign_key="systems.id", index=True, unique=True)
    enabled: bool = Field(default=True)
    state: str = Field(default="active", max_length=32)
    schedule_expr: str = Field(max_length=255)
    auth_mode: str = Field(max_length=32)
    captcha_provider: str = Field(default="ddddocr", max_length=64)
    max_retry: int = Field(default=3)
    last_triggered_at: datetime | None = None
    last_succeeded_at: datetime | None = None
    last_failed_at: datetime | None = None
    last_failure_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```
```
class SystemCrawlPolicy(BaseModel, table=True):
    __tablename__ = "system_crawl_policies"
    system_id: UUID = Field(foreign_key="systems.id", index=True, unique=True)
    enabled: bool = Field(default=True)
    state: str = Field(default="active", max_length=32)
    schedule_expr: str = Field(max_length=255)
    crawl_scope: str = Field(default="full", max_length=32)
    framework_hint: str | None = Field(default=None, max_length=32)
    max_pages: int | None = None
    last_triggered_at: datetime | None = None
    last_succeeded_at: datetime | None = None
    last_failed_at: datetime | None = None
    last_failure_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

- [ ] **Step 4: Add the Alembic migration**

Runbook for the migration:
- create both policy tables
- add timestamps and last-triggered audit fields
- add only queue/job fields that are required for policy-triggered job audit
- do not mix unrelated runner/published-job changes into this migration

- [ ] **Step 5: Run the schema tests again**

Run: `cd backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k runtime_policy`
Expected: PASS

- [ ] **Step 6: Commit the schema task**

```bash
git add backend/src/app/infrastructure/db/models/runtime_policies.py backend/src/app/infrastructure/db/models/systems.py backend/src/app/shared/enums.py backend/alembic/versions/0006_runtime_policies_and_queue_claims.py tests/backend/test_initial_schema.py
git commit -m "feat: add runtime policy schema"
```

---

## Task 2: Add Runtime Policy Repository, DTOs, and API

**Files:**
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/domains/control_plane/schemas.py`
- Create: `backend/src/app/domains/control_plane/runtime_policies.py`
- Create: `backend/src/app/api/endpoints/runtime_policies.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/api/deps.py`
- Test: `tests/backend/test_runtime_policies_api.py`

- [ ] **Step 1: Write failing runtime policy API tests**

```python
def test_put_auth_policy_upserts_system_policy(client, seeded_system):
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/auth-policy",
        json={"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "slider_captcha"},
    )
    assert response.status_code == 200
    assert response.json()["auth_mode"] == "slider_captcha"
```

```python
def test_put_crawl_policy_upserts_system_policy(client, seeded_system):
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": True, "schedule_expr": "0 */2 * * *", "crawl_scope": "incremental"},
    )
    assert response.status_code == 200
    assert response.json()["crawl_scope"] == "incremental"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_policies_api.py -v`
Expected: FAIL because the DTOs, repository methods, and routes do not exist

- [ ] **Step 3: Add runtime policy DTOs and repository methods**

```python
class UpdateSystemAuthPolicy(BaseModel):
    enabled: bool = True
    schedule_expr: str
    auth_mode: str
    captcha_provider: str = "ddddocr"
    captcha_config_json: dict[str, object] | None = None
    max_retry: int = 3
```
```
class UpdateSystemCrawlPolicy(BaseModel):
    enabled: bool = True
    schedule_expr: str
    crawl_scope: str = "full"
    framework_hint: str | None = None
    max_pages: int | None = None
```

- [ ] **Step 4: Add API endpoints and dependency wiring**

Routes to add:
- `GET /api/v1/systems/{system_id}/auth-policy`
- `PUT /api/v1/systems/{system_id}/auth-policy`
- `GET /api/v1/systems/{system_id}/crawl-policy`
- `PUT /api/v1/systems/{system_id}/crawl-policy`

Validation targets:
- allow `auth_mode` values `none`, `image_captcha`, `slider_captcha`, `sms_captcha`
- keep `sms_captcha` accepted at config level even though runtime returns `not_implemented`
- validate `crawl_scope` as `full | incremental`
- validate `state` as `active | paused`

- [ ] **Step 5: Run the runtime policy API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_policies_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit the runtime policy API task**

```bash
git add backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/service.py backend/src/app/domains/control_plane/schemas.py backend/src/app/domains/control_plane/runtime_policies.py backend/src/app/api/endpoints/runtime_policies.py backend/src/app/api/router.py backend/src/app/api/deps.py tests/backend/test_runtime_policies_api.py
git commit -m "feat: add runtime policy management api"
```

---

## Task 3: Add `control_plane` Scheduler and Worker Daemon Entry Points

**Files:**
- Create: `backend/src/app/runtime/worker_daemon.py`
- Create: `backend/src/app/runtime/scheduler_daemon.py`
- Modify: `backend/src/app/config/settings.py`
- Modify: `backend/src/app/workers/runner.py`
- Test: `tests/backend/test_runtime_daemons.py`
- Test: `tests/backend/test_worker_runner.py`

- [ ] **Step 1: Write failing daemon loop tests**

```python
@pytest.mark.anyio
async def test_worker_daemon_runs_until_idle_once(fake_worker_runner):
    processed = await run_worker_iteration(fake_worker_runner, max_jobs=1)
    assert processed == 1
```

```python
@pytest.mark.anyio
async def test_scheduler_daemon_scans_enabled_policies(fake_scheduler):
    triggered = await run_scheduler_iteration(fake_scheduler)
    assert triggered >= 0
```

```python
@pytest.mark.anyio
async def test_scheduler_iteration_honors_batch_size(fake_scheduler):
    triggered = await run_scheduler_iteration(fake_scheduler, batch_size=2)
    assert triggered <= 2
```

- [ ] **Step 2: Run the daemon tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_daemons.py ../tests/backend/test_worker_runner.py -v`
Expected: FAIL because daemon entrypoints and safe-claim behavior do not exist

- [ ] **Step 3: Add polling settings and daemon loops**

```python
class Settings(BaseSettings):
    worker_poll_interval_ms: int = 1000
    scheduler_scan_interval_ms: int = 60000
    scheduler_batch_size: int = 100
    auth_scheduler_enabled: bool = True
    crawl_scheduler_enabled: bool = True
    playwright_headless: bool = True
    ddddocr_enabled: bool = True
```
```
async def run_worker_forever(worker: WorkerRunner, *, poll_interval_ms: int) -> None:
    while True:
        handled = await worker.run_once()
        if not handled:
            await anyio.sleep(poll_interval_ms / 1000)
```

- [ ] **Step 4: Tighten `WorkerRunner` job-claim semantics for daemon use**

Implementation target:
- single-worker safe behavior now
- explicit place for future `FOR UPDATE SKIP LOCKED`
- no duplicate processing inside one polling loop
- scheduler loops must consume `SCHEDULER_BATCH_SIZE` when scanning due policies

- [ ] **Step 5: Run the daemon and worker tests**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_daemons.py ../tests/backend/test_worker_runner.py -v`
Expected: PASS

- [ ] **Step 6: Commit the daemon task**

```bash
git add backend/src/app/runtime/worker_daemon.py backend/src/app/runtime/scheduler_daemon.py backend/src/app/config/settings.py backend/src/app/workers/runner.py tests/backend/test_runtime_daemons.py tests/backend/test_worker_runner.py
git commit -m "feat: add control plane runtime daemons"
```

---

## Task 4: Add Captcha Solver Abstraction and `ddddocr` Integration

**Files:**
- Create: `backend/src/app/domains/auth_service/captcha_solver.py`
- Modify: `backend/src/app/domains/auth_service/schemas.py`
- Test: `tests/backend/test_captcha_solver.py`

- [ ] **Step 1: Write failing captcha solver tests**

```python
def test_ddddocr_solver_returns_image_solution(fake_ddddocr):
    solver = DdddOcrCaptchaSolver(ocr_client=fake_ddddocr)
    solution = solver.solve_image(CaptchaChallenge(kind="image_captcha", image_bytes=b"fake"))
    assert solution.text == "ABCD"
```

```python
def test_ddddocr_solver_returns_slider_offset(fake_ddddocr):
    solver = DdddOcrCaptchaSolver(ocr_client=fake_ddddocr)
    solution = solver.solve_slider(CaptchaChallenge(kind="slider_captcha", image_bytes=b"bg", puzzle_bytes=b"piece"))
    assert solution.offset_x == 42
```

```python
def test_sms_captcha_is_reserved_but_not_implemented(fake_ddddocr):
    solver = DdddOcrCaptchaSolver(ocr_client=fake_ddddocr)
    with pytest.raises(CaptchaNotImplementedError):
        solver.solve_sms(CaptchaChallenge(kind="sms_captcha"))
```

```python
def test_solver_is_disabled_when_ddddocr_flag_is_false(settings):
    settings.ddddocr_enabled = False
    solver = build_captcha_solver(settings=settings)
    with pytest.raises(CaptchaDisabledError):
        solver.solve_image(CaptchaChallenge(kind="image_captcha", image_bytes=b"fake"))
```

- [ ] **Step 2: Run the solver tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_captcha_solver.py -v`
Expected: FAIL because the solver abstraction and `ddddocr` adapter do not exist

- [ ] **Step 3: Add challenge/solution models and solver contract**

```python
class CaptchaChallenge(BaseModel):
    kind: str
    image_bytes: bytes | None = None
    puzzle_bytes: bytes | None = None
```
```
class CaptchaSolution(BaseModel):
    text: str | None = None
    offset_x: int | None = None
    confidence: float | None = None
```

- [ ] **Step 4: Implement the `ddddocr` adapter**

Implementation notes:
- isolate the import so tests can fake it
- keep image and slider solving in one place
- return structured errors for unsupported challenge kinds
- expose an explicit `solve_sms()` path that raises `not_implemented` in first version
- respect `DDDDOCR_ENABLED`; when disabled, return a deterministic disabled/not-implemented style error instead of attempting OCR

- [ ] **Step 5: Run the solver tests**

Run: `cd backend && uv run pytest ../tests/backend/test_captcha_solver.py -v`
Expected: PASS

- [ ] **Step 6: Commit the captcha solver task**

```bash
git add backend/src/app/domains/auth_service/captcha_solver.py backend/src/app/domains/auth_service/schemas.py tests/backend/test_captcha_solver.py
git commit -m "feat: add ddddocr captcha solver"
```

---

## Task 5: Upgrade Auth Login Flow to a Captcha-Aware State Machine

**Files:**
- Modify: `backend/src/app/domains/auth_service/browser_login.py`
- Modify: `backend/src/app/domains/auth_service/service.py`
- Modify: `backend/src/app/domains/auth_service/schemas.py`
- Modify: `tests/backend/test_browser_login.py`
- Modify: `tests/backend/test_auth_service.py`
- Modify: `tests/backend/test_auth_job.py`

- [ ] **Step 1: Write failing auth tests for captcha-aware login**

```python
@pytest.mark.anyio
async def test_login_solves_slider_before_submit(monkeypatch):
    result = await PlaywrightBrowserLoginAdapter(captcha_solver=solver).login(
        login_url="https://example.com/login",
        username="user",
        password="pass",
        auth_type="slider_captcha",
        selectors={"username": "#u", "password": "#p", "submit": "button", "slider_handle": ".slider"},
    )
    assert result.storage_state is not None
```

```python
@pytest.mark.anyio
async def test_login_respects_playwright_headless_setting(monkeypatch):
    result = await PlaywrightBrowserLoginAdapter(
        captcha_solver=solver,
        playwright_headless=False,
    ).login(
        login_url="https://example.com/login",
        username="user",
        password="pass",
        auth_type="none",
        selectors={"username": "#u", "password": "#p", "submit": "button"},
    )
    assert result.storage_state is not None
```

```python
@pytest.mark.anyio
async def test_refresh_auth_state_never_returns_storage_state_to_api(auth_service, seeded_system_credentials):
    result = await auth_service.refresh_auth_state(system_id=seeded_system_credentials.system_id)
    assert "storage_state" not in result.model_dump()
```

```python
@pytest.mark.anyio
async def test_sms_auth_mode_returns_not_implemented(auth_service, seeded_system_credentials):
    result = await auth_service.refresh_auth_state(system_id=seeded_system_credentials.system_id)
    assert result.status == "failed"
    assert result.message == "not_implemented"
```

- [ ] **Step 2: Run the auth tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_browser_login.py ../tests/backend/test_auth_service.py ../tests/backend/test_auth_job.py -v`
Expected: FAIL because the login flow does not branch on captcha type and the auth result contract is too thin

- [ ] **Step 3: Refactor the login adapter into explicit states**

Target states:
- open page
- fill credentials
- detect captcha
- solve captcha branch
- submit
- wait for success signal
- capture storage state

- [ ] **Step 4: Tighten auth-state persistence boundaries**

Implementation target:
- persist `AuthState.storage_state` only inside server-side storage
- expose only metadata/fingerprints/result codes in service results
- classify failures as `page_open_failed`, `captcha_detect_failed`, `captcha_solve_failed`, `auth_state_empty`, `unsupported_auth_mode`, or `not_implemented`
- thread `PLAYWRIGHT_HEADLESS` into browser launch so runtime behavior matches deployment config

- [ ] **Step 5: Run the auth/login tests**

Run: `cd backend && uv run pytest ../tests/backend/test_browser_login.py ../tests/backend/test_auth_service.py ../tests/backend/test_auth_job.py -v`
Expected: PASS

- [ ] **Step 6: Commit the captcha-aware auth task**

```bash
git add backend/src/app/domains/auth_service/browser_login.py backend/src/app/domains/auth_service/service.py backend/src/app/domains/auth_service/schemas.py tests/backend/test_browser_login.py tests/backend/test_auth_service.py tests/backend/test_auth_job.py
git commit -m "feat: add captcha aware auth refresh flow"
```

---

## Task 6: Replace Null Extractors with Real Crawl Extraction

**Files:**
- Modify: `backend/src/app/domains/crawler_service/extractors/router_runtime.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Modify: `backend/src/app/infrastructure/db/models/crawl.py`
- Modify: `tests/backend/test_crawler_service.py`
- Modify: `tests/backend/test_crawl_job.py`

- [ ] **Step 1: Write failing crawl extraction tests**

```python
@pytest.mark.anyio
async def test_run_crawl_persists_menu_nodes_and_elements(crawler_service, seeded_auth_state):
    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")
    assert result.status == "success"
    assert result.menus_saved >= 1
    assert result.elements_saved >= 1
```

```python
@pytest.mark.anyio
async def test_run_crawl_marks_degraded_when_extractors_return_no_pages(crawler_service, seeded_auth_state):
    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="incremental")
    assert result.status == "success"
    assert result.pages_saved == 0
```

```python
@pytest.mark.anyio
async def test_run_crawl_never_returns_raw_storage_state(crawler_service, seeded_auth_state):
    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")
    assert "storage_state" not in result.model_dump()
```

- [ ] **Step 2: Run the crawl tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_crawler_service.py ../tests/backend/test_crawl_job.py -v`
Expected: FAIL because the extractors still return empty results and crawl metadata is incomplete

- [ ] **Step 3: Implement runtime route extraction and DOM menu traversal**

Implementation target:
- collect page candidates from runtime route hints when present
- traverse menus using stable locators
- collect buttons, inputs, tables, query forms, tabs, and pagers
- never use dynamic IDs as the primary locator
- consume only a server-injected browser context, never expose or return raw `storage_state`

- [ ] **Step 4: Persist crawl failure and warning metadata**

Add result fields and persistence for:
- `failure_reason`
- `warning_messages`
- `degraded`

- [ ] **Step 5: Run the crawl tests**

Run: `cd backend && uv run pytest ../tests/backend/test_crawler_service.py ../tests/backend/test_crawl_job.py -v`
Expected: PASS

- [ ] **Step 6: Commit the crawl extraction task**

```bash
git add backend/src/app/domains/crawler_service/extractors/router_runtime.py backend/src/app/domains/crawler_service/extractors/dom_menu.py backend/src/app/domains/crawler_service/service.py backend/src/app/infrastructure/db/models/crawl.py tests/backend/test_crawler_service.py tests/backend/test_crawl_job.py
git commit -m "feat: add real crawl extractors"
```

---

## Task 7: Add Policy-Driven Auth and Crawl Scheduling

**Files:**
- Create: `backend/src/app/domains/control_plane/runtime_scheduler.py`
- Modify: `backend/src/app/jobs/auth_refresh_job.py`
- Modify: `backend/src/app/jobs/crawl_job.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Test: `tests/backend/test_runtime_scheduler.py`
- Modify: `tests/backend/test_scheduler_service.py`

- [ ] **Step 1: Write failing runtime scheduler tests**

```python
@pytest.mark.anyio
async def test_runtime_scheduler_enqueues_due_auth_policy(runtime_scheduler, seeded_auth_policy, db_session):
    triggered = await runtime_scheduler.trigger_due_auth_policies()
    assert triggered == 1
```

```python
@pytest.mark.anyio
async def test_runtime_scheduler_enqueues_due_crawl_policy(runtime_scheduler, seeded_crawl_policy, db_session):
    triggered = await runtime_scheduler.trigger_due_crawl_policies()
    assert triggered == 1
```

```python
@pytest.mark.anyio
async def test_runtime_scheduler_updates_last_triggered_at(runtime_scheduler, seeded_auth_policy, db_session):
    await runtime_scheduler.trigger_due_auth_policies()
    db_session.refresh(seeded_auth_policy)
    assert seeded_auth_policy.last_triggered_at is not None
```

- [ ] **Step 2: Run the scheduler tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_scheduler.py ../tests/backend/test_scheduler_service.py -v`
Expected: FAIL because there is no system-level auth/crawl scheduler

- [ ] **Step 3: Implement the runtime scheduler**

Implementation target:
- read active auth/crawl policies
- evaluate cron
- skip duplicate enqueue in the same minute
- enqueue `auth_refresh` and `crawl` with `policy_id` and `trigger_source="scheduler"`
- enforce `SCHEDULER_BATCH_SIZE` as the per-iteration scan limit
- update `last_triggered_at` when a policy is actually enqueued

- [ ] **Step 4: Keep cross-domain handoff inside `control_plane`**

Implementation target:
- `crawler_service` returns facts only
- `CrawlJobHandler` is the only place that appends `asset_compile`
- job payload/result payload captures policy-trigger metadata for audit
- `crawl_job` payload/result payload must not include raw `storage_state`
- crawler-facing interfaces accept injected context/session objects, not serialized auth state blobs
- `AuthRefreshJobHandler` and `CrawlJobHandler` must update `last_succeeded_at` / `last_failed_at` / `last_failure_message` on their bound policies

- [ ] **Step 5: Run the scheduler tests**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_scheduler.py ../tests/backend/test_scheduler_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit the runtime scheduler task**

```bash
git add backend/src/app/domains/control_plane/runtime_scheduler.py backend/src/app/jobs/auth_refresh_job.py backend/src/app/jobs/crawl_job.py backend/src/app/domains/control_plane/service.py backend/src/app/domains/control_plane/repository.py tests/backend/test_runtime_scheduler.py tests/backend/test_scheduler_service.py
git commit -m "feat: add runtime auth and crawl scheduler"
```

---

## Task 8: Final Integration, Docs, and Verification

**Files:**
- Modify: `backend/README.md`
- Modify: `docs/base_info.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-04-02-backend-auth-crawl-runtime-design.md`
- Add: `docs/superpowers/plans/2026-04-02-backend-auth-crawl-runtime-plan.md`

- [ ] **Step 1: Write the final verification checklist into docs**

Checklist content to add:
- how to start worker daemon
- how to start scheduler daemon
- how to manage auth/crawl policies
- how to manually verify test system 1 and test system 2
- how `.env` controls `SCHEDULER_BATCH_SIZE`, `PLAYWRIGHT_HEADLESS`, and `DDDDOCR_ENABLED`
- how `sms_captcha` is configured but intentionally returns `not_implemented` in first version
- how to observe policy audit fields after scheduler trigger and after worker success/failure

- [ ] **Step 2: Run the focused backend test suites**

Run:
```bash
cd backend && uv run pytest \
  ../tests/backend/test_runtime_policies_api.py \
  ../tests/backend/test_runtime_scheduler.py \
  ../tests/backend/test_runtime_daemons.py \
  ../tests/backend/test_captcha_solver.py \
  ../tests/backend/test_browser_login.py \
  ../tests/backend/test_auth_service.py \
  ../tests/backend/test_auth_job.py \
  ../tests/backend/test_crawler_service.py \
  ../tests/backend/test_crawl_job.py \
  ../tests/backend/test_worker_runner.py -v
```
Expected: PASS

- [ ] **Step 3: Run a database-backed smoke test**

Run:
```bash
cd backend && uv run pytest \
  ../tests/backend/test_job_submission_api.py \
  ../tests/backend/test_runtime_policies_api.py \
  ../tests/backend/test_runtime_scheduler.py -v
```
Expected: PASS

- [ ] **Step 4: Update changelog and finalize reviewed docs**

```markdown
- 新增 system 级 auth/crawl 策略、control_plane runtime daemon、ddddocr 验证码求解器与真实 crawler extractor。
```

- [ ] **Step 5: Commit the final integration task**

```bash
git add backend/README.md docs/base_info.md CHANGELOG.md docs/superpowers/specs/2026-04-02-backend-auth-crawl-runtime-design.md docs/superpowers/plans/2026-04-02-backend-auth-crawl-runtime-plan.md
git commit -m "docs: finalize auth crawl runtime plan"
```

---

## Execution Notes

- Implement in task order. Do not start Task 4 before Tasks 1-3 land because the daemon and policy boundaries define where captcha and crawl orchestration belong.
- Keep commits small and scoped to one task.
- If Playwright site behavior blocks deterministic CI, isolate browser-heavy checks behind fakes in unit tests and reserve real-site validation for the documented manual smoke checklist.
- Do not let `crawler_service` enqueue `asset_compile` directly. That handoff must stay in `control_plane` runtime code.
- Do not expose raw `storage_state` through API responses, generic logs, or result payloads.
