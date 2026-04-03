# AI Playwright Platform Asset Compiler and Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the asset compiler layer so crawl facts can be transformed into page assets, standard checks, module plans, and drift classifications that power deterministic execution.

**Architecture:** Build a focused `asset_compiler` domain that consumes `crawl_snapshots`, computes structure fingerprints, materializes `page_assets` and `page_checks`, and classifies asset health as `safe`, `suspect`, or `stale`. Keep real Playwright execution out of scope except for compile-time validation hooks and compile-job handling.

**Tech Stack:** FastAPI, SQLModel, PostgreSQL, Redis, pytest

---

## File Structure

**Files to Create:**
- `backend/src/app/domains/asset_compiler/schemas.py`
- `backend/src/app/domains/asset_compiler/service.py`
- `backend/src/app/domains/asset_compiler/fingerprints.py`
- `backend/src/app/domains/asset_compiler/check_templates.py`
- `backend/src/app/domains/asset_compiler/module_plan_builder.py`
- `backend/src/app/jobs/asset_compile_job.py`

**Files to Modify:**
- `backend/src/app/shared/enums.py` - Add compile state and drift state enums
- `backend/src/app/infrastructure/db/models/assets.py` - Complete asset/compiler fields
- `backend/src/app/infrastructure/db/models/jobs.py` - Support compile job outcomes
- `backend/src/app/workers/runner.py` - Register `asset_compile`
- `backend/src/app/api/endpoints/assets.py` - Report compile job identifiers and result shape
- `backend/alembic/versions/0003_asset_compiler_and_drift.py`
- `backend/README.md`

**Tests to Create:**
- `tests/backend/test_asset_compiler_service.py`
- `tests/backend/test_asset_fingerprints.py`
- `tests/backend/test_asset_compile_job.py`
- `tests/backend/test_assets_api.py`

**Docs to Modify:**
- `CHANGELOG.md`

---

## Task 1: Extend Asset Schema for Compiler and Drift States

**Files:**
- Modify: `backend/src/app/shared/enums.py`
- Modify: `backend/src/app/infrastructure/db/models/assets.py`
- Create: `backend/alembic/versions/0003_asset_compiler_and_drift.py`
- Test: `tests/backend/test_asset_fingerprints.py`

- [ ] **Step 1: Write the failing schema test for drift-aware asset fields**

```python
def test_page_asset_exposes_drift_tracking_fields():
    assert hasattr(PageAsset, "compiled_from_snapshot_id")
    assert hasattr(PageAsset, "status")
    assert hasattr(AssetSnapshot, "diff_score_vs_previous")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_fingerprints.py -v -k drift_fields`
Expected: FAIL because asset compiler fields are incomplete

- [ ] **Step 3: Add asset compiler enums and fields**

Include:

- `AssetStatus` with `safe`, `suspect`, `stale`
- `PageCheck.success_rate`
- `ModulePlan.plan_version`
- `AssetSnapshot.navigation_hash`, `key_locator_hash`, `semantic_summary_hash`, `diff_score_vs_previous`

- [ ] **Step 4: Create migration `0003_asset_compiler_and_drift.py`**

- [ ] **Step 5: Run schema tests**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_fingerprints.py -v -k drift_fields`
Expected: PASS

- [ ] **Step 6: Commit asset schema extension**

```bash
git add backend/src/app/shared/enums.py backend/src/app/infrastructure/db/models/assets.py backend/alembic/versions/0003_asset_compiler_and_drift.py tests/backend/test_asset_fingerprints.py
git commit -m "feat: extend asset schema for compiler and drift"
```

---

## Task 2: Implement Fingerprint and Drift Calculation Utilities

**Files:**
- Create: `backend/src/app/domains/asset_compiler/fingerprints.py`
- Test: `tests/backend/test_asset_fingerprints.py`

- [ ] **Step 1: Write failing fingerprint tests**

```python
def test_build_structure_fingerprint_is_stable_for_same_page_shape():
    fingerprint_a = build_page_fingerprint(page_payload)
    fingerprint_b = build_page_fingerprint(page_payload)
    assert fingerprint_a == fingerprint_b
```

```python
def test_diff_score_increases_when_key_locators_change():
    diff = compare_fingerprints(old_fp, new_fp)
    assert diff.score > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_fingerprints.py -v`
Expected: FAIL because fingerprint helpers do not exist

- [ ] **Step 3: Implement deterministic fingerprint builders**

Add helpers for:

- navigation hash
- key locator hash
- semantic summary hash
- aggregate structure hash

- [ ] **Step 4: Implement diff scoring and state mapping**

Map diff score ranges to:

- `safe`
- `suspect`
- `stale`

Use constants, not magic numbers.

- [ ] **Step 5: Run fingerprint tests**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_fingerprints.py -v`
Expected: PASS

- [ ] **Step 6: Commit fingerprint utilities**

```bash
git add backend/src/app/domains/asset_compiler/fingerprints.py tests/backend/test_asset_fingerprints.py
git commit -m "feat: add asset fingerprint and drift utilities"
```

---

## Task 3: Implement Standard Check Templates and Module Plan Builder

**Files:**
- Create: `backend/src/app/domains/asset_compiler/check_templates.py`
- Create: `backend/src/app/domains/asset_compiler/module_plan_builder.py`
- Test: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: Write failing tests for standard checks and module plans**

```python
def test_build_standard_checks_for_table_page_returns_page_open_and_table_render():
    checks = build_standard_checks(page_summary="用户管理", has_table=True)
    assert {"page_open", "table_render"} <= {check.check_code for check in checks}
```

```python
def test_build_module_plan_for_table_render_contains_expected_steps():
    plan = build_module_plan(check_code="table_render", page_context=page_context)
    assert plan.steps_json[0]["module"] == "auth.inject_state"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_compiler_service.py -v -k "standard_checks or module_plan"`
Expected: FAIL because builders do not exist

- [ ] **Step 3: Implement standard check template selection**

Support at least:

- `page_open`
- `table_render`
- `open_create_modal`

Use page facts only. Do not call Playwright in this step.

- [ ] **Step 4: Implement module plan builder**

Generated plans must compose deterministic steps such as:

- `auth.inject_state`
- `nav.menu_chain`
- `page.wait_ready`
- `assert.table_visible`

- [ ] **Step 5: Run builder tests**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_compiler_service.py -v -k "standard_checks or module_plan"`
Expected: PASS

- [ ] **Step 6: Commit check templates and plan builder**

```bash
git add backend/src/app/domains/asset_compiler/check_templates.py backend/src/app/domains/asset_compiler/module_plan_builder.py tests/backend/test_asset_compiler_service.py
git commit -m "feat: add standard checks and module plan builder"
```

---

## Task 4: Implement Asset Compiler Service

**Files:**
- Create: `backend/src/app/domains/asset_compiler/schemas.py`
- Create: `backend/src/app/domains/asset_compiler/service.py`
- Test: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: Write failing compiler service tests**

```python
async def test_compile_snapshot_creates_page_assets_and_checks(asset_compiler_service, seeded_crawl_snapshot):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_crawl_snapshot.id)
    assert result.status == "success"
    assert result.assets_created >= 1
    assert result.checks_created >= 1
```

```python
async def test_compile_snapshot_marks_asset_suspect_when_drift_is_medium(asset_compiler_service, seeded_previous_snapshot):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=seeded_previous_snapshot.id)
    assert result.drift_state in {"safe", "suspect", "stale"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_compiler_service.py -v`
Expected: FAIL because compiler service does not exist

- [ ] **Step 3: Implement compile flow**

Compiler service must:

- load crawl snapshot pages and elements
- build fingerprints
- compare against previous asset snapshot
- create or update `page_assets`
- create or update `page_checks`
- create `module_plans`
- create `asset_snapshots`

- [ ] **Step 4: Persist intent aliases for initial page discovery**

Generate minimal aliases from:

- system name/code
- page title
- route path

Keep fuzzy learning and manual curation out of scope.

- [ ] **Step 5: Run compiler service tests**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_compiler_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit asset compiler service**

```bash
git add backend/src/app/domains/asset_compiler tests/backend/test_asset_compiler_service.py
git commit -m "feat: add asset compiler service"
```

---

## Task 5: Implement Asset Compile Job and Assets API

**Files:**
- Create: `backend/src/app/jobs/asset_compile_job.py`
- Modify: `backend/src/app/workers/runner.py`
- Modify: `backend/src/app/api/endpoints/assets.py`
- Test: `tests/backend/test_asset_compile_job.py`
- Test: `tests/backend/test_assets_api.py`

- [ ] **Step 1: Write failing compile-job and assets API tests**

```python
async def test_asset_compile_job_completes_and_persists_assets(job_runner, queued_compile_job):
    await job_runner.run_once()
    refreshed = await load_job(queued_compile_job.id)
    assert refreshed.status == "completed"
```

```python
def test_compile_assets_endpoint_returns_job_id(client, seeded_snapshot):
    response = client.post(
        f"/api/v1/snapshots/{seeded_snapshot.id}/compile-assets",
        json={"compile_scope": "impacted_pages_only"},
    )
    assert response.status_code == 202
    assert response.json()["job_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_compile_job.py ../tests/backend/test_assets_api.py -v`
Expected: FAIL because compile job handler and enriched API are incomplete

- [ ] **Step 3: Implement compile job handler and worker dispatch**

The handler must:

- call `AssetCompilerService.compile_snapshot`
- update queue state
- persist compile summary

- [ ] **Step 4: Enrich assets API responses**

Return:

- `job_id`
- `snapshot_id`
- `job_type`
- accepted status

- [ ] **Step 5: Run compile-job and assets API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_compile_job.py ../tests/backend/test_assets_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit compile job and API**

```bash
git add backend/src/app/jobs/asset_compile_job.py backend/src/app/workers/runner.py backend/src/app/api/endpoints/assets.py tests/backend/test_asset_compile_job.py tests/backend/test_assets_api.py
git commit -m "feat: add asset compile job and assets api"
```

---

## Task 6: Update Docs and Verify Compiler Flow

**Files:**
- Modify: `backend/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document compile and drift workflow**

Document:

- compile trigger
- standard checks produced
- drift states and meaning
- where to inspect generated assets

- [ ] **Step 2: Run full compiler-related test suite**

Run: `cd backend && uv run pytest ../tests/backend/test_asset_fingerprints.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_asset_compile_job.py ../tests/backend/test_assets_api.py -v`
Expected: PASS

- [ ] **Step 3: Commit docs updates**

```bash
git add backend/README.md CHANGELOG.md
git commit -m "docs: document asset compiler and drift workflow"
```

---

## Done Criteria

This plan is complete when the new project can:

- compute stable crawl fingerprints
- create/update page assets and standard checks from crawl snapshots
- classify asset drift as `safe`, `suspect`, or `stale`
- persist module plans and asset snapshots
- execute an `asset_compile` job through the worker
- pass the compiler and drift test suite

At that point, the project is ready for real runner execution, script rendering, and published job scheduling.
