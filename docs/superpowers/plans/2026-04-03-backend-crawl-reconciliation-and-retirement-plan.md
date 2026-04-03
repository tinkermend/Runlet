# Backend Crawl Reconciliation and Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic backend reconciliation flow that retires deleted page assets and dependent checks after a high-quality `full crawl`, disables aliases, pauses published jobs, and blocks execution of retired targets.

**Architecture:** Keep `crawler_service` as the fact collector only. Extend `asset_compiler` into a two-phase compiler plus reconciliation unit that updates active assets first and then retires missing pages or blocking dependencies. Let `control_plane` and `runner_service` consume lifecycle truth rather than re-deriving it, so alias resolution, scheduling, and worker execution all converge on the same retirement state.

**Tech Stack:** FastAPI, Pydantic v2, SQLModel, Alembic, PostgreSQL, APScheduler, Playwright Python, pytest

---

## File Structure

**Files to Create:**

- `backend/src/app/domains/asset_compiler/reconciliation.py`
  Responsibility: compare current snapshot truth with active asset/check truth, compute created/updated/retired sets, and return deterministic retirement actions.
- `backend/alembic/versions/0009_asset_reconciliation_retirement.py`
  Responsibility: add lifecycle and audit columns/tables needed for retirement semantics.
- `tests/backend/test_asset_reconciliation.py`
  Responsibility: focused compiler/reconciliation regression coverage for page retirement, key-element retirement, alias disabling, and quality-gate protection.

**Files to Modify:**

- `backend/src/app/shared/enums.py`
  Add lifecycle and retirement enums for assets, checks, aliases, and blocked execution reasons.
- `backend/src/app/infrastructure/db/models/assets.py`
  Add lifecycle columns to `PageAsset` and `PageCheck`, alias disable metadata, and reconciliation audit table/model.
- `backend/src/app/infrastructure/db/models/jobs.py`
  Add pause-reason metadata to `PublishedJob` so scheduler state can explain system-driven pauses.
- `backend/src/app/domains/asset_compiler/schemas.py`
  Expand compile result DTOs to return explicit reconciliation outputs instead of only counts and a single drift state.
- `backend/src/app/domains/asset_compiler/service.py`
  Split compilation into update-first plus retire-after phases, persist asset/check lifecycle truth, and emit deterministic cascade decisions.
- `backend/src/app/jobs/asset_compile_job.py`
  Serialize and persist the richer reconciliation result payload.
- `backend/src/app/domains/control_plane/repository.py`
  Resolve only active aliases/assets/checks, expose helper queries for retirement-aware execution targets, execute alias-disable cascades, and surface richer page-check list status.
- `backend/src/app/domains/control_plane/service.py`
  Reject retired assets/checks deterministically and coordinate alias/job cascade execution when reconciliation retires dependencies.
- `backend/src/app/domains/control_plane/schemas.py`
  Expose lifecycle-aware page-check list items and retirement-aware request status payloads.
- `backend/src/app/domains/runner_service/scheduler.py`
  Add service helpers to pause published jobs due to asset retirement and keep registry behavior aligned with paused jobs.
- `backend/src/app/jobs/run_check_job.py`
  Add final execution-time retirement guard so queued work created before retirement is still blocked.
- `backend/src/app/api/endpoints/page_checks.py`
  Reuse updated schemas when listing checks or triggering runs against retired targets.
- `tests/backend/test_asset_compiler_service.py`
  Cover lifecycle state transitions and reconciliation output counts.
- `tests/backend/test_asset_compile_job.py`
  Cover richer compile result serialization and audit persistence.
- `tests/backend/test_control_plane_service.py`
  Cover active-only resolution and retirement-based request rejection.
- `tests/backend/test_page_checks_api.py`
  Cover lifecycle-aware page-check listing and run rejection against retired targets.
- `tests/backend/test_scheduler_service.py`
  Cover automatic pause semantics and scheduler skip behavior for retirement-paused jobs.
- `tests/backend/test_run_check_job.py`
  Cover worker-side blocking of pre-enqueued jobs after retirement.
- `tests/backend/test_initial_schema.py`
  Assert new lifecycle, alias-disable, pause-reason, and reconciliation tables/columns exist.
- `CHANGELOG.md`
  Record the implementation plan.

**Existing References to Read While Executing:**

- `docs/superpowers/specs/2026-04-03-backend-crawl-reconciliation-and-retirement-design.md`
- `backend/src/app/domains/asset_compiler/service.py`
- `backend/src/app/domains/control_plane/repository.py`
- `backend/src/app/domains/control_plane/service.py`
- `backend/src/app/domains/runner_service/scheduler.py`
- `backend/src/app/jobs/run_check_job.py`

---

### Task 1: Add Lifecycle Persistence and Reconciliation Contracts

**Files:**

- Create: `backend/alembic/versions/0009_asset_reconciliation_retirement.py`
- Modify: `backend/src/app/shared/enums.py`
- Modify: `backend/src/app/infrastructure/db/models/assets.py`
- Modify: `backend/src/app/infrastructure/db/models/jobs.py`
- Modify: `backend/src/app/domains/asset_compiler/schemas.py`
- Test: `tests/backend/test_initial_schema.py`
- Test: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: Write the failing schema tests for lifecycle columns and reconciliation output**

```python
def test_page_asset_exposes_lifecycle_columns():
    assert hasattr(PageAsset, "drift_status")
    assert hasattr(PageAsset, "lifecycle_status")
    assert hasattr(PageAsset, "retired_by_snapshot_id")


def test_compile_snapshot_result_exposes_reconciliation_counts():
    assert "assets_retired" in CompileSnapshotResult.__dataclass_fields__
    assert "checks_retired" in CompileSnapshotResult.__dataclass_fields__
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py ../tests/backend/test_asset_compiler_service.py -v -k "lifecycle or reconciliation"`
Expected: FAIL because lifecycle columns, reconciliation fields, and new schema metadata do not exist yet.

- [ ] **Step 3: Add enums, model fields, and migration skeleton**

```python
class AssetLifecycleStatus(StrEnum):
    ACTIVE = "active"
    RETIRED_MISSING = "retired_missing"
    RETIRED_REPLACED = "retired_replaced"
    RETIRED_MANUAL = "retired_manual"
```

Add:

- `PageAsset.drift_status`, `PageAsset.lifecycle_status`, `retired_reason`, `retired_at`, `retired_by_snapshot_id`
- `PageCheck.lifecycle_status`, `retired_reason`, `retired_at`, `retired_by_snapshot_id`, `blocking_dependency_json`
- `IntentAlias.is_active`, `disabled_reason`, `disabled_at`, `disabled_by_snapshot_id`
- `PublishedJob.pause_reason`, `paused_by_snapshot_id`, `paused_by_asset_id`, `paused_by_page_check_id`
- reconciliation audit table/model for per-snapshot retirement details, including retired asset/check ids, reason categories, and paused published job ids

- [ ] **Step 4: Expand compile result DTOs for explicit reconciliation output**

```python
@dataclass(frozen=True)
class CompileSnapshotResult:
    snapshot_id: UUID
    status: str
    assets_created: int
    assets_updated: int
    assets_retired: int
    checks_created: int
    checks_updated: int
    checks_retired: int
    alias_disable_decision_count: int
    published_job_pause_decision_count: int
    alias_ids_to_disable: list[UUID]
    published_job_ids_to_pause: list[UUID]
    retire_reasons: list[dict[str, object]]
```

- [ ] **Step 5: Run the focused tests to verify the schema contracts pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py ../tests/backend/test_asset_compiler_service.py -v -k "lifecycle or reconciliation"`
Expected: PASS

- [ ] **Step 6: Commit the persistence contract changes**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/shared/enums.py backend/src/app/infrastructure/db/models/assets.py backend/src/app/infrastructure/db/models/jobs.py backend/src/app/domains/asset_compiler/schemas.py backend/alembic/versions/0009_asset_reconciliation_retirement.py tests/backend/test_initial_schema.py tests/backend/test_asset_compiler_service.py
git commit -m "feat: add lifecycle and reconciliation schema"
```

---

### Task 2: Implement Snapshot Reconciliation and Retirement in Asset Compiler

**Files:**

- Create: `backend/src/app/domains/asset_compiler/reconciliation.py`
- Modify: `backend/src/app/domains/asset_compiler/service.py`
- Modify: `backend/src/app/jobs/asset_compile_job.py`
- Test: `tests/backend/test_asset_reconciliation.py`
- Test: `tests/backend/test_asset_compiler_service.py`
- Test: `tests/backend/test_asset_compile_job.py`

- [ ] **Step 1: Write the failing reconciliation tests for page retirement and quality gating**

```python
@pytest.mark.anyio
async def test_compile_snapshot_retires_missing_page_after_high_quality_full_crawl(
    asset_compiler_service,
    seeded_retirement_baseline,
    seeded_missing_page_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_missing_page_snapshot.id)

    assert result.assets_retired == 1
    assert result.checks_retired >= 1
```

```python
@pytest.mark.anyio
async def test_compile_snapshot_skips_retirement_when_snapshot_is_degraded(
    asset_compiler_service,
    seeded_retirement_baseline,
    seeded_degraded_full_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_degraded_full_snapshot.id)

    assert result.assets_retired == 0
```

```python
@pytest.mark.anyio
async def test_compile_snapshot_retires_check_when_blocking_menu_chain_is_missing(
    asset_compiler_service,
    seeded_menu_dependent_baseline,
    seeded_missing_menu_chain_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_missing_menu_chain_snapshot.id)

    assert result.checks_retired == 1
    assert result.retire_reasons[0]["reason"] == "missing_menu_chain"
```

```python
@pytest.mark.anyio
async def test_compile_snapshot_retires_check_when_key_element_is_missing(
    asset_compiler_service,
    seeded_key_element_baseline,
    seeded_missing_key_element_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_missing_key_element_snapshot.id)

    assert result.checks_retired == 1
    assert result.retire_reasons[0]["reason"] == "missing_key_element"
```

```python
@pytest.mark.anyio
async def test_compile_snapshot_reactivates_retired_asset_when_high_quality_full_crawl_finds_it_again(
    asset_compiler_service,
    seeded_retired_asset,
    seeded_reappeared_page_snapshot,
):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_reappeared_page_snapshot.id)

    assert result.assets_updated >= 1
```

- [ ] **Step 2: Run the focused compiler tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_asset_reconciliation.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_asset_compile_job.py -v`
Expected: FAIL because the compiler only updates/creates assets and never computes retirement sets.

- [ ] **Step 3: Extract deterministic reconciliation helpers**

```python
@dataclass(frozen=True)
class RetirementDecision:
    page_asset_id: UUID
    page_check_ids: list[UUID]
    reason: str
```

In `reconciliation.py`:

- build active truth from current DB rows
- build current truth from the new snapshot
- detect missing pages using `route_path` as the primary stable page identity key
- reserve `system_code + canonical_page_name` as a future fallback only for systems where route keys cannot be trusted
- detect missing blocking dependencies
- derive `blocking_dependency_json` from `module_plan.steps_json` and `assertion_schema`, with a deterministic shape such as:

```python
{
    "menu_chain": ["系统管理", "用户管理"],
    "required_elements": [
        {"kind": "button", "text": "新增用户"},
        {"kind": "table", "role": "table", "text": "用户列表"},
    ],
}
```

- map `menu_chain` against snapshot menu truth and `required_elements` against snapshot page elements
- skip all retirement decisions if any quality-gate condition fails:
  - `snapshot.crawl_type == "full"`
  - `snapshot.degraded is False`
  - `snapshot.quality_score is not None and snapshot.quality_score >= QUALITY_GATE_MIN_SCORE`
  - `current_page_count >= ACTIVE_PAGE_COUNT_COLLAPSE_RATIO * previous_active_page_count`
- write an audit warning payload when the page-count collapse guard blocks retirement

- [ ] **Step 4: Rework `AssetCompilerService.compile_snapshot()` into update-then-retire flow**

Implement in this order:

1. compile/update assets still present in the snapshot
2. reactivate previously retired assets/checks when the high-quality `full` snapshot proves they are present again
3. compute retirement decisions against remaining active rows
4. mark only `page_asset/page_check` lifecycle retirement metadata inside the compiler transaction
5. emit cascade decisions for `alias_ids_to_disable` and `published_job_ids_to_pause` without executing cross-domain updates
6. encode `retire_reasons` with at least `reason`, `page_asset_id`, `page_check_ids`, and `published_job_ids`
7. write reconciliation audit details as retirement decisions, not completed cascade outcomes
8. return explicit counts in `CompileSnapshotResult`

- [ ] **Step 5: Extend asset compile job serialization for reconciliation payloads**

```python
payload["assets_retired"] = result.assets_retired
payload["checks_retired"] = result.checks_retired
payload["alias_disable_decision_count"] = result.alias_disable_decision_count
payload["published_job_pause_decision_count"] = result.published_job_pause_decision_count
payload["retire_reasons"] = result.retire_reasons
payload["alias_ids_to_disable"] = [str(alias_id) for alias_id in result.alias_ids_to_disable]
payload["published_job_ids_to_pause"] = [str(job_id) for job_id in result.published_job_ids_to_pause]
```

- [ ] **Step 6: Run the focused compiler tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_asset_reconciliation.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_asset_compile_job.py -v`
Expected: PASS

- [ ] **Step 7: Commit the compiler reconciliation changes**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/reconciliation.py backend/src/app/domains/asset_compiler/service.py backend/src/app/jobs/asset_compile_job.py tests/backend/test_asset_reconciliation.py tests/backend/test_asset_compiler_service.py tests/backend/test_asset_compile_job.py
git commit -m "feat: reconcile retired assets after full crawl"
```

---

### Task 3: Pause Dependent Published Jobs and Surface Lifecycle-Aware Read Models

**Files:**

- Modify: `backend/src/app/domains/runner_service/scheduler.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/schemas.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/api/endpoints/page_checks.py`
- Test: `tests/backend/test_scheduler_service.py`
- Test: `tests/backend/test_control_plane_service.py`
- Test: `tests/backend/test_page_checks_api.py`

- [ ] **Step 1: Write the failing service tests for pause propagation and active-only resolution**

```python
@pytest.mark.anyio
async def test_pause_jobs_for_retired_page_check_marks_published_jobs_paused(
    published_job_service,
    seeded_published_job,
    db_session,
):
    paused = await published_job_service.pause_jobs_for_retired_page_check(
        page_check_id=seeded_published_job.page_check_id,
        snapshot_id=uuid4(),
        reason="asset_retired_missing",
    )

    assert paused == 1
```

```python
@pytest.mark.anyio
async def test_submit_check_request_ignores_disabled_alias_and_retired_asset(
    control_plane_service,
    seeded_retired_asset,
):
    with pytest.raises(HTTPException, match="asset is retired"):
        await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="table_render",
        )
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_scheduler_service.py ../tests/backend/test_control_plane_service.py ../tests/backend/test_page_checks_api.py -v -k "retired or paused or lifecycle"`
Expected: FAIL because published jobs cannot yet be paused by reconciliation and repository resolution still uses only drift status.

- [ ] **Step 3: Add scheduler helper to pause jobs for retired assets/checks**

```python
async def pause_jobs_for_retired_page_check(
    self,
    *,
    page_check_id: UUID,
    snapshot_id: UUID,
    reason: str,
) -> int:
    ...
```

Persist:

- `state = paused`
- `pause_reason = reason`
- `paused_by_snapshot_id = snapshot_id`
- `paused_by_page_check_id = page_check_id`

- [ ] **Step 4: Update control-plane read models and repository filters**

Implement:

- resolve only `IntentAlias.is_active == True`
- resolve only `PageAsset.lifecycle_status == active`
- resolve only `PageCheck.lifecycle_status == active`
- expose both `drift_status` and `lifecycle_status` in page-check list items
- reject retired targets with explicit `409` semantics and do not fall back to `realtime_probe`
- add repository helpers that disable aliases from compiler decisions in one transaction

- [ ] **Step 5: Have `ControlPlaneService` coordinate pause propagation after reconciliation**

When compile/reconciliation returns retired checks:

- disable aliases from `alias_ids_to_disable`
- pause dependent published jobs through `PublishedJobService`
- keep `control_plane` as the only cross-domain orchestrator
- treat `retired_missing` as a hard stop for manual/API resolution instead of probe fallback
- treat `aliases_disabled` and `published_jobs_paused` as executed cascade counts owned by control plane, while compiler-side payloads stay decision-oriented (`alias_disable_decision_count`, `published_job_pause_decision_count`, ids, reasons)

- [ ] **Step 6: Run the focused tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_scheduler_service.py ../tests/backend/test_control_plane_service.py ../tests/backend/test_page_checks_api.py -v -k "retired or paused or lifecycle"`
Expected: PASS

- [ ] **Step 7: Commit the pause propagation and read-model changes**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/runner_service/scheduler.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/schemas.py backend/src/app/domains/control_plane/service.py backend/src/app/api/endpoints/page_checks.py tests/backend/test_scheduler_service.py tests/backend/test_control_plane_service.py tests/backend/test_page_checks_api.py
git commit -m "feat: pause published jobs for retired assets"
```

---

### Task 4: Block Retired Targets in API and Worker Execution Paths

**Files:**

- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/jobs/run_check_job.py`
- Test: `tests/backend/test_page_checks_api.py`
- Test: `tests/backend/test_run_check_job.py`

- [ ] **Step 1: Write the failing tests for run rejection and queued-job blocking**

```python
def test_post_page_check_run_rejects_retired_page_check(client, seeded_retired_page_check):
    response = client.post(
        f"/api/v1/page-checks/{seeded_retired_page_check.id}:run",
        json={"strictness": "balanced", "time_budget_ms": 20000, "triggered_by": "manual"},
    )

    assert response.status_code == 409
```

```python
@pytest.mark.anyio
async def test_run_check_job_skips_when_target_was_retired_after_enqueue(
    job_runner,
    queued_run_check_job,
    retire_run_check_target,
    db_session,
):
    await job_runner.run_once()

    refreshed = db_session.get(QueuedJob, queued_run_check_job.id)
    assert refreshed.status == "skipped"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_page_checks_api.py ../tests/backend/test_run_check_job.py -v -k "retired or skipped"`
Expected: FAIL because manual run requests and worker jobs do not yet enforce lifecycle blocking.

- [ ] **Step 3: Reject retired targets in `ControlPlaneService.run_page_check()` and request resolution**

Implement explicit conflict behavior:

```python
if target.page_check.lifecycle_status != "active":
    raise HTTPException(status_code=409, detail="page check is retired")
```

- [ ] **Step 4: Add final worker-side retirement guard before runtime execution**

In `RunCheckJobHandler`:

- reload current `page_asset/page_check`
- if target is retired or linked `published_job` is paused by retirement, mark queue item `skipped`
- write `failure_message = "asset_retired_missing"`
- do not invoke `RunnerService`

- [ ] **Step 5: Run the focused tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_page_checks_api.py ../tests/backend/test_run_check_job.py -v -k "retired or skipped"`
Expected: PASS

- [ ] **Step 6: Commit the execution-blocking changes**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/service.py backend/src/app/jobs/run_check_job.py tests/backend/test_page_checks_api.py tests/backend/test_run_check_job.py
git commit -m "feat: block retired assets at execution time"
```

---

### Task 5: Run Full Regression Sweep and Update Docs

**Files:**

- Modify: `CHANGELOG.md`
- Reference: `docs/superpowers/specs/2026-04-03-backend-crawl-reconciliation-and-retirement-design.md`
- Reference: `docs/superpowers/plans/2026-04-03-backend-crawl-reconciliation-and-retirement-plan.md`

- [ ] **Step 1: Add the implementation note to the changelog entry**

```md
- 落地后端采集同步一致性与资产退役实现，新增 reconciliation、生命周期状态、调度暂停与执行阻断闭环。
```

- [ ] **Step 2: Run the targeted backend regression suite**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py ../tests/backend/test_asset_reconciliation.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_asset_compile_job.py ../tests/backend/test_control_plane_service.py ../tests/backend/test_page_checks_api.py ../tests/backend/test_scheduler_service.py ../tests/backend/test_run_check_job.py -v`
Expected: PASS

- [ ] **Step 3: Run the broader backend smoke suite for collateral impact**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_assets_api.py ../tests/backend/test_check_requests_api.py ../tests/backend/test_scheduler_runtime.py -v`
Expected: PASS

- [ ] **Step 4: Review `git diff` to confirm only intended reconciliation files changed**

Run: `cd /Users/wangpei/src/singe/Runlet && git diff --stat`
Expected: shows schema/model/compiler/control-plane/scheduler/worker/tests/changelog changes only.

- [ ] **Step 5: Commit the final regression and doc touch-ups**

```bash
cd /Users/wangpei/src/singe/Runlet
git add CHANGELOG.md
git commit -m "test: cover crawl reconciliation retirement flow"
```

---

## Notes for Execution

- Treat `status == stale` and `lifecycle_status == retired_missing` as different concerns. Do not collapse them back into one field during implementation.
- Do not retire anything from `incremental` or low-quality `full` snapshots.
- Update assets that still exist before retiring missing ones, or you will create avoidable empty windows.
- Keep `control_plane` as the only cross-domain coordinator. `asset_compiler` should return decisions, not pause jobs by itself.
- For key-element retirement, only use dependencies already declared by `module_plan` / `assertion_schema`; do not invent free-form DOM heuristics.
