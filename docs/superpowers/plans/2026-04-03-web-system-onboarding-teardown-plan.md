# Web System Onboarding and Teardown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `openweb web-system add/remove` so a YAML manifest can onboard a web test system through the formal backend chain and fully remove an onboarded system with no database or scheduler residue.

**Architecture:** Keep `cli` as a thin command surface. Add a dedicated `SystemAdminService` under `control_plane` plus a focused repository and bootstrap module. `add` will parse YAML, encrypt plaintext credentials with a `.env` secret, create/update system metadata, then drive the existing formal chain synchronously by using `ControlPlaneService` job acceptance plus in-process job handlers for auth, crawl, and compile before publishing the selected `page_check`. `remove` will resolve the target by `system_code`, remove APScheduler jobs first, then delete all related rows in a deterministic dependency order and verify nothing remains.

**Tech Stack:** Python 3.12, Typer, PyYAML, AnyIO, FastAPI service wiring, Pydantic v2, SQLModel, APScheduler, pytest

---

## File Structure

**Files to Create:**

- `backend/src/app/domains/control_plane/system_admin_schemas.py`
  Responsibility: YAML manifest DTOs, onboarding/teardown result DTOs, and delete-count summaries.
- `backend/src/app/domains/control_plane/system_admin_repository.py`
  Responsibility: upsert `systems/system_credentials`, resolve candidate `page_check`, collect related identifiers, locate queued compile jobs, and execute deterministic teardown deletes.
- `backend/src/app/domains/control_plane/system_admin_service.py`
  Responsibility: orchestration entrypoints for `onboard_system()` and `teardown_system()`.
- `backend/src/app/domains/control_plane/system_admin_bootstrap.py`
  Responsibility: assemble `SystemAdminService` with DB session, `ControlPlaneService`, `SchedulerRegistry`, `CredentialCrypto`, and in-process job executor built from the existing worker handlers.
- `cli/src/openweb_cli/backend_bootstrap.py`
  Responsibility: monorepo adapter that locates sibling `backend/src`, imports backend bootstrap helpers, and returns a ready `SystemAdminService`.
- `cli/src/openweb_cli/manifest_loader.py`
  Responsibility: load YAML via `yaml.safe_load`, validate through backend manifest schemas, and resolve `--file` / `--system-code` rules for `remove`.
- `tests/backend/test_system_admin_service.py`
  Responsibility: service-level coverage for manifest validation, credential encryption, onboarding flow, publish target selection, teardown cleanup, and scheduler removal.
- `tests/cli/test_web_system_cli.py`
  Responsibility: Typer command coverage for `web-system add/remove`, argument validation, and result output.

**Files to Modify:**

- `backend/src/app/config/settings.py`
  Add the local credential crypto secret setting read from `.env`.
- `backend/src/app/domains/auth_service/crypto.py`
  Add encrypt support while preserving backward-compatible decrypt support for existing `enc:` and `enc-b64:` fixtures.
- `backend/src/app/jobs/crawl_job.py`
  Persist the successful `snapshot_id` into `QueuedJob.result_payload` so onboarding can deterministically locate the follow-up compile job.
- `cli/src/openweb_cli/main.py`
  Add the `web-system` command group plus `add/remove` subcommands.
- `cli/pyproject.toml`
  Add CLI runtime/test dependencies needed for YAML loading and async service invocation.
- `CHANGELOG.md`
  Record the implementation plan and, during execution, record shipped onboarding/teardown support.

**Existing References to Read While Executing:**

- `docs/superpowers/specs/2026-04-03-web-system-onboarding-teardown-design.md`
- `backend/src/app/domains/control_plane/service.py`
- `backend/src/app/workers/runner.py`
- `backend/src/app/jobs/auth_refresh_job.py`
- `backend/src/app/jobs/crawl_job.py`
- `backend/src/app/jobs/asset_compile_job.py`
- `backend/src/app/domains/auth_service/crypto.py`
- `cli/src/openweb_cli/main.py`
- `tests/backend/test_crawl_job.py`

---

### Task 1: Define Manifest and Credential Encryption Contracts

**Files:**

- Create: `backend/src/app/domains/control_plane/system_admin_schemas.py`
- Modify: `backend/src/app/config/settings.py`
- Modify: `backend/src/app/domains/auth_service/crypto.py`
- Test: `tests/backend/test_system_admin_service.py`

- [ ] **Step 1: Write the failing schema and crypto tests**

```python
def test_web_system_manifest_accepts_nested_yaml_sections():
    manifest = WebSystemManifest.model_validate(
        {
            "system": {"code": "hotgo_test3", "name": "hotgo", "base_url": "https://hotgo.facms.cn", "framework_type": "react"},
            "credential": {"login_url": "https://hotgo.facms.cn/admin#/login?redirect=/dashboard", "username": "admin", "password": "123456", "auth_type": "image_captcha", "selectors": {"username": "input[name=username]"}},
            "auth_policy": {"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "image_captcha", "captcha_provider": "ddddocr"},
            "crawl_policy": {"enabled": True, "schedule_expr": "0 */2 * * *", "crawl_scope": "full"},
            "publish": {"check_goal": "table_render", "schedule_expr": "*/30 * * * *", "enabled": True},
        }
    )

    assert manifest.system.code == "hotgo_test3"
    assert manifest.publish.check_goal == "table_render"
```

```python
def test_local_credential_crypto_round_trips_with_env_secret():
    crypto = LocalCredentialCrypto(secret="test-secret")
    encrypted = crypto.encrypt("admin")

    assert encrypted.startswith("enc-b64:")
    assert crypto.decrypt(encrypted) == "admin"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py -v -k "manifest or crypto"`
Expected: FAIL because the manifest models and `encrypt()` contract do not exist yet.

- [ ] **Step 3: Add manifest DTOs and local crypto secret settings**

```python
class WebSystemManifest(BaseModel):
    system: SystemManifestSection
    credential: CredentialManifestSection
    auth_policy: AuthPolicyManifestSection
    crawl_policy: CrawlPolicyManifestSection
    publish: PublishManifestSection
```

```python
class Settings(BaseSettings):
    credential_crypto_secret: str = Field(default="runlet-local-credential-secret")
```

- [ ] **Step 4: Extend `LocalCredentialCrypto` with an encrypt API**

```python
class CredentialCrypto(Protocol):
    def encrypt(self, value: str, *, secret_ref: str | None = None) -> str: ...
    def decrypt(self, value: str, *, secret_ref: str | None = None) -> str: ...
```

```python
def encrypt(self, value: str, *, secret_ref: str | None = None) -> str:
    payload = f"{self.secret}:{value}".encode("utf-8")
    return "enc-b64:" + base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
```

Preserve existing decrypt support for the current `enc:` fixtures so existing auth tests keep passing.

- [ ] **Step 5: Run the focused tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py -v -k "manifest or crypto"`
Expected: PASS

- [ ] **Step 6: Commit the manifest and crypto contracts**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/system_admin_schemas.py backend/src/app/config/settings.py backend/src/app/domains/auth_service/crypto.py tests/backend/test_system_admin_service.py
git commit -m "feat: add web system manifest and credential crypto contracts"
```

---

### Task 2: Build the Onboarding Service and In-Process Formal Job Execution

**Files:**

- Create: `backend/src/app/domains/control_plane/system_admin_repository.py`
- Create: `backend/src/app/domains/control_plane/system_admin_service.py`
- Create: `backend/src/app/domains/control_plane/system_admin_bootstrap.py`
- Modify: `backend/src/app/jobs/crawl_job.py`
- Test: `tests/backend/test_system_admin_service.py`
- Test: `tests/backend/test_crawl_job.py`

- [ ] **Step 1: Write the failing onboarding tests**

```python
@pytest.mark.anyio
async def test_onboard_system_creates_records_runs_jobs_and_publishes(
    system_admin_service,
    scheduler,
):
    result = await system_admin_service.onboard_system(manifest=build_hotgo_manifest())

    assert result.system_code == "hotgo_test3"
    assert result.page_check_id is not None
    assert result.published_job_id is not None
    assert f"published_job:{result.published_job_id}" in result.scheduler_job_ids
```

```python
@pytest.mark.anyio
async def test_onboard_system_fails_when_publish_goal_is_missing(
    system_admin_service,
):
    with pytest.raises(ValueError, match="page_check for goal table_render not found"):
        await system_admin_service.onboard_system(manifest=build_manifest_without_matching_check())
```

- [ ] **Step 2: Run the focused onboarding tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py ../tests/backend/test_crawl_job.py -v -k "onboard_system or snapshot_id"`
Expected: FAIL because there is no onboarding service, bootstrap wiring, publish-target selection, or crawl queue result contract for `snapshot_id`.

- [ ] **Step 3: Implement the repository helpers for upsert and target lookup**

```python
system = await repo.upsert_system(
    code=manifest.system.code,
    name=manifest.system.name,
    base_url=manifest.system.base_url,
    framework_type=manifest.system.framework_type,
)
await repo.upsert_system_credentials(
    system_id=system.id,
    login_url=manifest.credential.login_url,
    username_encrypted=crypto.encrypt(manifest.credential.username),
    password_encrypted=crypto.encrypt(manifest.credential.password),
    auth_type=manifest.credential.auth_type,
    selectors=manifest.credential.selectors,
)
```

Add a repository method that returns the deterministic active `page_check` for `publish.check_goal`, preferring the newest compiled asset and stable ordering by `page_asset.id`.

- [ ] **Step 4: Implement synchronous formal-chain orchestration in `SystemAdminService`**

Use this sequence:

```python
auth_job = await control_plane.refresh_auth(system_id=system.id)
await job_executor.run_auth_refresh(auth_job.job_id)

crawl_job = await control_plane.trigger_crawl(system_id=system.id, payload=CrawlTriggerRequest(...))
await job_executor.run_crawl(crawl_job.job_id)

snapshot_id = await repo.get_successful_crawl_snapshot_id(job_id=crawl_job.job_id)
compile_job = await repo.get_compile_job_for_snapshot(snapshot_id=snapshot_id)
await job_executor.run_asset_compile(compile_job.id)
```

Then resolve `page_check`, render a published script through `ControlPlaneService.create_published_job()`, and return the created IDs plus scheduler job ids.

- [ ] **Step 5: Persist `snapshot_id` on successful crawl jobs**

Update `backend/src/app/jobs/crawl_job.py` so a successful run writes:

```python
job.result_payload = {
    "status": "success",
    "snapshot_id": str(result.snapshot_id),
}
```

and extend `tests/backend/test_crawl_job.py` to assert the field is present. This removes ambiguity when locating the exact compile job created by the crawl handler.

- [ ] **Step 6: Bootstrap the service with real domain services and handlers**

Create `system_admin_bootstrap.py` that:

1. Opens an async DB session from `create_session_factory()`
2. Builds `ControlPlaneService` with `SchedulerRegistry`
3. Builds `AuthService`, `CrawlerService`, and `AssetCompilerService`
4. Reuses the worker job handlers to create a small in-process executor for auth/crawl/compile jobs

- [ ] **Step 7: Run the focused onboarding tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py ../tests/backend/test_crawl_job.py -v -k "onboard_system or snapshot_id"`
Expected: PASS

- [ ] **Step 8: Commit the onboarding service**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/system_admin_repository.py backend/src/app/domains/control_plane/system_admin_service.py backend/src/app/domains/control_plane/system_admin_bootstrap.py backend/src/app/jobs/crawl_job.py tests/backend/test_system_admin_service.py tests/backend/test_crawl_job.py
git commit -m "feat: add web system onboarding service"
```

---

### Task 3: Implement Full Teardown with Scheduler Cleanup and Residue Verification

**Files:**

- Modify: `backend/src/app/domains/control_plane/system_admin_repository.py`
- Modify: `backend/src/app/domains/control_plane/system_admin_service.py`
- Test: `tests/backend/test_system_admin_service.py`

- [ ] **Step 1: Write the failing teardown tests**

```python
@pytest.mark.anyio
async def test_teardown_system_removes_related_rows_and_scheduler_jobs(
    onboarded_system,
    system_admin_service,
    scheduler,
):
    result = await system_admin_service.teardown_system(system_code="vben_test1")

    assert result.system_found is True
    assert result.remaining_scheduler_job_ids == []
    assert result.remaining_reference_tables == []
```

```python
@pytest.mark.anyio
async def test_teardown_system_is_idempotent_when_system_is_missing(system_admin_service):
    result = await system_admin_service.teardown_system(system_code="missing-system")
    assert result.system_found is False
```

- [ ] **Step 2: Run the focused teardown tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py -v -k "teardown_system"`
Expected: FAIL because teardown orchestration, delete ordering, and residue checks do not exist yet.

- [ ] **Step 3: Implement identifier collection and deterministic delete order**

Use repository helpers to collect:

- `job_run_ids`
- `published_job_ids`
- `page_check_ids`
- `page_asset_ids`
- `intent_alias_ids`
- `module_plan_ids`
- `asset_snapshot_ids`
- `reconciliation_audit_ids`
- `page_ids`
- `menu_node_ids`
- `page_element_ids`
- `crawl_snapshot_ids`
- `auth_state_ids`
- `system_credential_ids`
- `auth_policy_ids`
- `crawl_policy_ids`
- `execution_plan_ids`
- `execution_run_ids`
- `execution_artifact_ids`
- `execution_request_ids`
- `script_render_ids`
- `queued_job_ids`

Then delete in the explicit order from the spec:

```python
for model, ids in [
    (JobRun, job_run_ids),
    (PublishedJob, published_job_ids),
    (QueuedJob, queued_job_ids),
    (ExecutionArtifact, execution_artifact_ids),
    (ScriptRender, script_render_ids),
    (ExecutionRun, execution_run_ids),
    (ExecutionPlan, execution_plan_ids),
    (ExecutionRequest, execution_request_ids),
    (AssetReconciliationAudit, reconciliation_audit_ids),
    (AssetSnapshot, asset_snapshot_ids),
    (ModulePlan, module_plan_ids),
    (IntentAlias, intent_alias_ids),
    (PageCheck, page_check_ids),
    (PageAsset, page_asset_ids),
    (PageElement, page_element_ids),
    (MenuNode, menu_node_ids),
    (Page, page_ids),
    (CrawlSnapshot, crawl_snapshot_ids),
    (AuthState, auth_state_ids),
    (SystemCredential, system_credential_ids),
    (SystemAuthPolicy, auth_policy_ids),
    (SystemCrawlPolicy, crawl_policy_ids),
    (System, [system_id]),
]:
    await repo.delete_by_ids(model=model, ids=ids)
```

- [ ] **Step 4: Remove scheduler jobs before DB deletion and verify no residue remains**

```python
scheduler.remove_job(build_auth_policy_job_id(system_id))
scheduler.remove_job(build_crawl_policy_job_id(system_id))
for published_job_id in published_job_ids:
    scheduler.remove_job(build_published_job_id(published_job_id))
```

After commit, query the repository for any remaining rows referencing `system_id`; fail the service if anything remains.

- [ ] **Step 5: Run the focused teardown tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py -v -k "teardown_system"`
Expected: PASS

- [ ] **Step 6: Commit the teardown implementation**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/system_admin_repository.py backend/src/app/domains/control_plane/system_admin_service.py tests/backend/test_system_admin_service.py
git commit -m "feat: add web system teardown cleanup"
```

---

### Task 4: Wire the CLI Commands, YAML Loader, and Backend Bootstrap Adapter

**Files:**

- Create: `cli/src/openweb_cli/backend_bootstrap.py`
- Create: `cli/src/openweb_cli/manifest_loader.py`
- Modify: `cli/src/openweb_cli/main.py`
- Modify: `cli/pyproject.toml`
- Test: `tests/cli/test_web_system_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
def test_web_system_add_invokes_onboard_service(runner, monkeypatch, tmp_path):
    manifest_path = tmp_path / "hotgo.yaml"
    manifest_path.write_text("system:\\n  code: hotgo_test3\\n...", encoding="utf-8")

    result = runner.invoke(app, ["web-system", "add", "--file", str(manifest_path)])

    assert result.exit_code == 0
    assert "published_job_id" in result.stdout
```

```python
def test_web_system_remove_rejects_missing_locator(runner):
    result = runner.invoke(app, ["web-system", "remove"])
    assert result.exit_code != 0
    assert "--system-code" in result.stdout or "--file" in result.stdout
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `cd /Users/wangpei/src/singe/Runlet/cli && uv run pytest ../tests/cli/test_web_system_cli.py -v`
Expected: FAIL because the command group, YAML loader, and backend bootstrap adapter do not exist yet.

- [ ] **Step 3: Add CLI dependencies and YAML loader**

Update `cli/pyproject.toml` to include:

```toml
dependencies = [
  "typer>=0.12",
  "pyyaml>=6.0",
  "anyio>=4.0",
]

[dependency-groups]
dev = ["pytest>=8.3"]
```

Implement `manifest_loader.py` with:

```python
def load_manifest(path: Path) -> WebSystemManifest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return WebSystemManifest.model_validate(payload)
```

- [ ] **Step 4: Add the CLI command group and monorepo backend adapter**

Implement a small adapter that prepends sibling `backend/src` to `sys.path`, imports `create_system_admin_service`, and closes the async session after each command. In `main.py`:

```python
web_system_app = typer.Typer()
app.add_typer(web_system_app, name="web-system")

@web_system_app.command("add")
def add_web_system(file: Path = typer.Option(..., exists=True)):
    manifest = load_manifest(file)
    result = anyio.run(run_onboard, manifest)
    typer.echo(f"published_job_id={result.published_job_id}")
```

```python
@web_system_app.command("remove")
def remove_web_system(file: Path | None = None, system_code: str | None = None):
    target_code = resolve_remove_target(file=file, system_code=system_code)
    result = anyio.run(run_teardown, target_code)
```

- [ ] **Step 5: Run the CLI tests to verify they pass**

Run: `cd /Users/wangpei/src/singe/Runlet/cli && uv run pytest ../tests/cli/test_web_system_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit the CLI integration**

```bash
cd /Users/wangpei/src/singe/Runlet
git add cli/src/openweb_cli/backend_bootstrap.py cli/src/openweb_cli/manifest_loader.py cli/src/openweb_cli/main.py cli/pyproject.toml tests/cli/test_web_system_cli.py
git commit -m "feat: add web system cli commands"
```

---

### Task 5: Run Focused Verification and Update Changelog

**Files:**

- Modify: `CHANGELOG.md`
- Test: `tests/backend/test_system_admin_service.py`
- Test: `tests/cli/test_web_system_cli.py`

- [ ] **Step 1: Update `CHANGELOG.md` for the shipped feature**

Add one concise 2026-04-03 entry describing:

- YAML-driven `openweb web-system add/remove`
- `.env` secret-backed credential encryption
- in-process formal auth/crawl/compile orchestration for onboarding
- full DB and APScheduler cleanup on teardown

- [ ] **Step 2: Run the focused backend verification**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_system_admin_service.py -v`
Expected: PASS

- [ ] **Step 3: Run the focused CLI verification**

Run: `cd /Users/wangpei/src/singe/Runlet/cli && uv run pytest ../tests/cli/test_web_system_cli.py -v`
Expected: PASS

- [ ] **Step 4: Run the combined verification sweep**

Run: `cd /Users/wangpei/src/singe/Runlet && uv run --project backend pytest tests/backend/test_system_admin_service.py -v && uv run --project cli pytest tests/cli/test_web_system_cli.py -v`
Expected: PASS for both commands.

- [ ] **Step 5: Commit the verification and changelog update**

```bash
cd /Users/wangpei/src/singe/Runlet
git add CHANGELOG.md
git commit -m "docs: record web system onboarding and teardown support"
```

---

## Notes for the Implementer

- Follow `@superpowers/test-driven-development` while executing each task: write the failing test first, then the minimum implementation, then rerun the targeted tests.
- Use `@superpowers/verification-before-completion` before claiming the feature is done; the combined backend and CLI verification commands above are the minimum evidence.
- Keep the onboarding path deterministic. If more than one `table_render` check exists, use the repository ordering rules from the spec rather than ad hoc selection.
- Do not log plaintext credentials. Any debug or failure output must refer to `system_code`, URLs, or job IDs only.
