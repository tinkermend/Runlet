# APScheduler 统一调度改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 `published_jobs` 的自研 cron 扫描与未来 `runtime_policies` 的扫描式设计统一改造为“数据库为真相、APScheduler 为统一触发器、`control_plane` 为调度运行归属”的正式实现。

**Architecture:** 保持数据库中的 `published_jobs`、`system_auth_policies`、`system_crawl_policies` 为唯一调度真相源。新增 `SchedulerRegistry` 与 `SchedulerRuntime`，由 `scheduler daemon` 承载 APScheduler；到点后只做 enqueue，正式执行仍走 `queued_jobs -> worker`。现有 `runner_service/scheduler.py` 中的发布任务业务能力需要拆出为独立服务，旧的全量扫库逻辑最终退场。

**Tech Stack:** FastAPI, SQLModel, SQLAlchemy 2.x, Alembic, PostgreSQL, APScheduler, pytest, anyio

---

## File Structure

**Files to Create:**
- `backend/src/app/infrastructure/db/models/runtime_policies.py` - 系统级 `auth/crawl` 调度策略模型
- `backend/src/app/api/endpoints/runtime_policies.py` - `runtime_policies` 管理 API
- `backend/src/app/domains/control_plane/runtime_policies.py` - `runtime_policies` DTO 与 service helper
- `backend/src/app/domains/control_plane/scheduler_registry.py` - 数据库调度对象与 APScheduler job 的映射层
- `backend/src/app/runtime/scheduler_runtime.py` - APScheduler 宿主与 callback 装配
- `backend/src/app/runtime/scheduler_daemon.py` - 单实例 scheduler 常驻进程入口
- `tests/backend/test_runtime_policies_api.py` - `runtime_policies` API 测试
- `tests/backend/test_scheduler_registry.py` - registry / trigger 转换测试
- `tests/backend/test_scheduler_runtime.py` - APScheduler runtime 与 callback 测试
- `tests/backend/test_scheduler_daemon.py` - daemon 启动恢复测试

**Files to Modify:**
- `backend/pyproject.toml` - 引入 `apscheduler`
- `backend/src/app/shared/enums.py` - 新增 runtime policy state / trigger source 等枚举（如果缺失）
- `backend/src/app/infrastructure/db/models/jobs.py` - 为 policy-triggered job 补充必要审计字段或 payload 约束
- `backend/src/app/infrastructure/db/models/systems.py` - 挂接 runtime policy 关联（如果当前关系缺失）
- `backend/alembic/versions/0006_runtime_policies_and_scheduler_runtime.py` - runtime policy 与审计字段迁移
- `backend/src/app/domains/control_plane/repository.py` - 增加 runtime policy 读写与 scheduler 所需查询
- `backend/src/app/domains/control_plane/schemas.py` - 增加 runtime policy API DTO
- `backend/src/app/domains/control_plane/service.py` - 接入 published job / runtime policy 的 registry 同步
- `backend/src/app/api/router.py` - 注册 runtime policy 路由
- `backend/src/app/api/deps.py` - 装配 published job service / registry / runtime 依赖
- `backend/src/app/api/endpoints/assets.py` - 改从发布任务 service 导入 DTO，避免继续依赖 `runner_service/scheduler.py`
- `backend/src/app/jobs/published_job_trigger.py` - 保留单条发布任务触发逻辑并加入幂等检查入口
- `backend/src/app/jobs/auth_refresh_job.py` - 保留 `policy_id` / `scheduled_at` / `trigger_source` 审计快照
- `backend/src/app/jobs/crawl_job.py` - 保留 `policy_id` / `scheduled_at` / `trigger_source` 审计快照
- `backend/src/app/workers/runner.py` - 视 daemon 需求补充持续运行入口
- `backend/src/app/config/settings.py` - 新增 scheduler runtime 配置
- `backend/src/app/domains/runner_service/scheduler.py` - 逐步拆出 `PublishedJobService`，删除 `trigger_due_jobs()` 主链职责
- `tests/backend/conftest.py` - 更新 service fixture 与新测试夹具
- `tests/backend/test_published_jobs_api.py` - published job API 保持兼容并验证 registry 同步
- `tests/backend/test_scheduler_service.py` - 从扫库测试改为发布任务幂等/单条触发测试
- `backend/README.md` - 文档改为 APScheduler runtime 方案
- `CHANGELOG.md` - 记录实施计划与后续实现

**Recommended Service Split:**
- `backend/src/app/domains/runner_service/scheduler.py` 在第一阶段保留文件路径，先抽出 `PublishedJobService`
- 第二阶段新增 `backend/src/app/domains/control_plane/scheduler_registry.py`
- 第三阶段再清掉 `trigger_due_jobs()` 旧扫描逻辑，避免一开始就大范围改 import

---

## Task 1: Add Runtime Policy Schema and Migration

**Files:**
- Create: `backend/src/app/infrastructure/db/models/runtime_policies.py`
- Modify: `backend/src/app/infrastructure/db/models/systems.py`
- Modify: `backend/src/app/shared/enums.py`
- Modify: `backend/src/app/infrastructure/db/models/jobs.py`
- Create: `backend/alembic/versions/0006_runtime_policies_and_scheduler_runtime.py`
- Test: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: Write the failing schema tests**

```python
def test_runtime_policy_tables_exist(inspector):
    table_names = set(inspector.get_table_names())
    assert "system_auth_policies" in table_names
    assert "system_crawl_policies" in table_names


def test_runtime_policy_models_expose_expected_fields():
    assert hasattr(SystemAuthPolicy, "schedule_expr")
    assert hasattr(SystemAuthPolicy, "last_triggered_at")
    assert hasattr(SystemCrawlPolicy, "crawl_scope")
    assert hasattr(SystemCrawlPolicy, "enabled")
```

- [ ] **Step 2: Run the schema tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k runtime_policy`
Expected: FAIL because `runtime_policies` models and tables do not exist

- [ ] **Step 3: Add runtime policy models and required enums**

```python
class SystemAuthPolicy(BaseModel, table=True):
    __tablename__ = "system_auth_policies"
    system_id: UUID = Field(foreign_key="systems.id", index=True, unique=True)
    enabled: bool = Field(default=True)
    state: str = Field(default="active", max_length=32)
    schedule_expr: str = Field(max_length=255)
    auth_mode: str = Field(max_length=32)
    captcha_provider: str = Field(default="ddddocr", max_length=64)
    last_triggered_at: datetime | None = None


class SystemCrawlPolicy(BaseModel, table=True):
    __tablename__ = "system_crawl_policies"
    system_id: UUID = Field(foreign_key="systems.id", index=True, unique=True)
    enabled: bool = Field(default=True)
    state: str = Field(default="active", max_length=32)
    schedule_expr: str = Field(max_length=255)
    crawl_scope: str = Field(default="full", max_length=32)
    last_triggered_at: datetime | None = None
```

- [ ] **Step 4: Add the Alembic migration**

Runbook:
- create `system_auth_policies`
- create `system_crawl_policies`
- add only the queue/job audit fields needed for `policy_id` / `trigger_source` / `scheduled_at`
- do not mix unrelated crawler or runner refactors into this migration

- [ ] **Step 5: Run the schema tests again**

Run: `cd backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k runtime_policy`
Expected: PASS

- [ ] **Step 6: Commit the schema task**

```bash
git add backend/src/app/infrastructure/db/models/runtime_policies.py backend/src/app/infrastructure/db/models/systems.py backend/src/app/shared/enums.py backend/src/app/infrastructure/db/models/jobs.py backend/alembic/versions/0006_runtime_policies_and_scheduler_runtime.py tests/backend/test_initial_schema.py
git commit -m "feat: add runtime policy schema"
```

---

## Task 2: Extract Published Job Business Logic from Legacy Scheduler

**Files:**
- Modify: `backend/src/app/domains/runner_service/scheduler.py`
- Modify: `backend/src/app/jobs/published_job_trigger.py`
- Modify: `backend/src/app/api/endpoints/assets.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/api/deps.py`
- Modify: `tests/backend/conftest.py`
- Modify: `tests/backend/test_published_jobs_api.py`
- Modify: `tests/backend/test_scheduler_service.py`

- [ ] **Step 1: Replace the old scan-based test with service-oriented failing tests**

```python
@pytest.mark.anyio
async def test_published_job_service_triggers_single_job_once_per_minute(
    published_job_service,
    seeded_published_job,
    db_session,
):
    fixed_now = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)
    published_job_service.now_provider = lambda: fixed_now

    first = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=fixed_now,
    )
    second = await published_job_service.trigger_scheduled_job(
        published_job_id=seeded_published_job.id,
        scheduled_at=fixed_now,
    )

    assert first is True
    assert second is False
```

- [ ] **Step 2: Run the published job tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_published_jobs_api.py ../tests/backend/test_scheduler_service.py -v`
Expected: FAIL because `trigger_scheduled_job()` and the new service boundary do not exist

- [ ] **Step 3: Refactor `runner_service/scheduler.py` into a `PublishedJobService`-style API**

```python
class PublishedJobService:
    async def create_published_job(self, *, payload: CreatePublishedJobRequest) -> PublishedJobCreated: ...
    async def trigger_published_job(self, *, published_job_id: UUID, trigger_source: str = "manual") -> PublishedJobTriggerAccepted: ...
    async def list_published_job_runs(self, *, published_job_id: UUID) -> PublishedJobRunsList: ...
    async def trigger_scheduled_job(self, *, published_job_id: UUID, scheduled_at: datetime) -> bool: ...
```

Implementation notes:
- keep current API DTOs stable
- move “同一分钟去重”到单条发布任务触发逻辑
- stop exposing `trigger_due_jobs()` as the main entrypoint

- [ ] **Step 4: Update API / deps / fixtures to use the new service boundary**

Runbook:
- `assets.py` 改从新 service DTO 导入
- `ControlPlaneService` 继续只编排，不自己判断 cron
- `tests/backend/conftest.py` fixture 改为注入 published job service

- [ ] **Step 5: Run the published job tests again**

Run: `cd backend && uv run pytest ../tests/backend/test_published_jobs_api.py ../tests/backend/test_scheduler_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit the published job extraction**

```bash
git add backend/src/app/domains/runner_service/scheduler.py backend/src/app/jobs/published_job_trigger.py backend/src/app/api/endpoints/assets.py backend/src/app/domains/control_plane/service.py backend/src/app/api/deps.py tests/backend/conftest.py tests/backend/test_published_jobs_api.py tests/backend/test_scheduler_service.py
git commit -m "refactor: extract published job service"
```

---

## Task 3: Add APScheduler Registry and Published-Job Scheduling

**Files:**
- Create: `backend/src/app/domains/control_plane/scheduler_registry.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/api/deps.py`
- Modify: `tests/backend/conftest.py`
- Create: `tests/backend/test_scheduler_registry.py`
- Modify: `tests/backend/test_published_jobs_api.py`

- [ ] **Step 1: Write the failing registry tests**

```python
def test_scheduler_registry_builds_stable_job_ids():
    assert build_published_job_id("123") == "published_job:123"
    assert build_auth_policy_job_id("sys-1") == "auth_policy:sys-1"
    assert build_crawl_policy_job_id("sys-1") == "crawl_policy:sys-1"


@pytest.mark.anyio
async def test_registry_upserts_published_job_into_apscheduler(registry, seeded_published_job):
    await registry.upsert_published_job(seeded_published_job.id)
    job = registry.scheduler.get_job(f"published_job:{seeded_published_job.id}")
    assert job is not None
```

- [ ] **Step 2: Run the registry tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_scheduler_registry.py -v`
Expected: FAIL because `scheduler_registry.py` and `apscheduler` integration do not exist

- [ ] **Step 3: Add APScheduler dependency and implement `SchedulerRegistry`**

```python
class SchedulerRegistry:
    async def load_all_from_db(self) -> None: ...
    async def upsert_published_job(self, published_job_id: UUID) -> None: ...
    async def upsert_auth_policy(self, policy_id: UUID) -> None: ...
    async def upsert_crawl_policy(self, policy_id: UUID) -> None: ...
    def remove_job(self, job_id: str) -> None: ...
```

Implementation notes:
- 使用 `CronTrigger.from_crontab(...)`
- 统一 job id 命名
- 第一版不使用 APScheduler job store 持久化

- [ ] **Step 4: Sync published-job create/update flows into the registry**

Runbook:
- `create_published_job()` 写库成功后 `upsert_published_job(...)`
- `enabled=false` 或 `state!=active` 时走 `remove_job(...)`
- API 测试增加 “创建发布任务后 scheduler 内已有 job” 断言

- [ ] **Step 5: Run registry and published-job tests**

Run: `cd backend && uv run pytest ../tests/backend/test_scheduler_registry.py ../tests/backend/test_published_jobs_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit the registry task**

```bash
git add backend/pyproject.toml backend/src/app/domains/control_plane/scheduler_registry.py backend/src/app/domains/control_plane/service.py backend/src/app/api/deps.py tests/backend/conftest.py tests/backend/test_scheduler_registry.py tests/backend/test_published_jobs_api.py
git commit -m "feat: add APScheduler registry for published jobs"
```

---

## Task 4: Add Runtime Policy Repository, API, and Registry Sync

**Files:**
- Create: `backend/src/app/domains/control_plane/runtime_policies.py`
- Create: `backend/src/app/api/endpoints/runtime_policies.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/schemas.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/api/deps.py`
- Modify: `tests/backend/conftest.py`
- Create: `tests/backend/test_runtime_policies_api.py`
- Modify: `tests/backend/test_scheduler_registry.py`

- [ ] **Step 1: Write the failing runtime-policy API tests**

```python
def test_put_auth_policy_upserts_and_registers_scheduler_job(client, seeded_system, scheduler_runtime):
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/auth-policy",
        json={"enabled": True, "schedule_expr": "*/30 * * * *", "auth_mode": "slider_captcha"},
    )

    assert response.status_code == 200
    assert scheduler_runtime.scheduler.get_job(f"auth_policy:{seeded_system.id}") is not None


def test_put_crawl_policy_disables_scheduler_job_when_enabled_false(client, seeded_system, scheduler_runtime):
    client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": True, "schedule_expr": "0 */2 * * *", "crawl_scope": "incremental"},
    )
    response = client.put(
        f"/api/v1/systems/{seeded_system.id}/crawl-policy",
        json={"enabled": False, "schedule_expr": "0 */2 * * *", "crawl_scope": "incremental"},
    )

    assert response.status_code == 200
    assert scheduler_runtime.scheduler.get_job(f"crawl_policy:{seeded_system.id}") is None
```

- [ ] **Step 2: Run the runtime-policy tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_policies_api.py ../tests/backend/test_scheduler_registry.py -v`
Expected: FAIL because repository methods, API routes, and registry sync for policies do not exist

- [ ] **Step 3: Implement runtime policy DTOs, repository methods, and service operations**

```python
class UpdateSystemAuthPolicy(BaseModel):
    enabled: bool = True
    schedule_expr: str
    auth_mode: str
    captcha_provider: str = "ddddocr"


class UpdateSystemCrawlPolicy(BaseModel):
    enabled: bool = True
    schedule_expr: str
    crawl_scope: str = "full"
```

Repository methods to add:
- `get_system_auth_policy(system_id)`
- `upsert_system_auth_policy(system_id, payload)`
- `get_system_crawl_policy(system_id)`
- `upsert_system_crawl_policy(system_id, payload)`
- `list_active_auth_policies()`
- `list_active_crawl_policies()`

- [ ] **Step 4: Register the new API routes and sync them into the registry**

Routes:
- `GET /api/v1/systems/{system_id}/auth-policy`
- `PUT /api/v1/systems/{system_id}/auth-policy`
- `GET /api/v1/systems/{system_id}/crawl-policy`
- `PUT /api/v1/systems/{system_id}/crawl-policy`

Sync rules:
- 写库成功后立即 `upsert_*`
- `enabled=false` 或 `state!=active` 时立即 `remove_job`

- [ ] **Step 5: Run the runtime-policy tests again**

Run: `cd backend && uv run pytest ../tests/backend/test_runtime_policies_api.py ../tests/backend/test_scheduler_registry.py -v`
Expected: PASS

- [ ] **Step 6: Commit the runtime-policy API task**

```bash
git add backend/src/app/domains/control_plane/runtime_policies.py backend/src/app/api/endpoints/runtime_policies.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/schemas.py backend/src/app/domains/control_plane/service.py backend/src/app/api/router.py backend/src/app/api/deps.py tests/backend/conftest.py tests/backend/test_runtime_policies_api.py tests/backend/test_scheduler_registry.py
git commit -m "feat: add runtime policy scheduler APIs"
```

---

## Task 5: Add Scheduler Runtime, Daemon, and End-to-End Scheduling Callbacks

**Files:**
- Create: `backend/src/app/runtime/scheduler_runtime.py`
- Create: `backend/src/app/runtime/scheduler_daemon.py`
- Modify: `backend/src/app/config/settings.py`
- Modify: `backend/src/app/jobs/published_job_trigger.py`
- Modify: `backend/src/app/jobs/auth_refresh_job.py`
- Modify: `backend/src/app/jobs/crawl_job.py`
- Modify: `backend/src/app/workers/runner.py`
- Create: `tests/backend/test_scheduler_runtime.py`
- Create: `tests/backend/test_scheduler_daemon.py`
- Modify: `tests/backend/test_scheduler_service.py`
- Modify: `tests/backend/test_worker_runner.py`

- [ ] **Step 1: Write the failing runtime and daemon tests**

```python
@pytest.mark.anyio
async def test_scheduler_runtime_restores_jobs_from_database(scheduler_runtime, seeded_published_job, seeded_auth_policy):
    await scheduler_runtime.start()
    assert scheduler_runtime.scheduler.get_job(f"published_job:{seeded_published_job.id}") is not None
    assert scheduler_runtime.scheduler.get_job(f"auth_policy:{seeded_auth_policy.system_id}") is not None


@pytest.mark.anyio
async def test_published_job_callback_enqueues_run_check_once(scheduler_runtime, seeded_published_job, db_session):
    fixed_now = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)
    await scheduler_runtime.trigger_published_job_now(seeded_published_job.id, scheduled_at=fixed_now)
    await scheduler_runtime.trigger_published_job_now(seeded_published_job.id, scheduled_at=fixed_now)

    queued_jobs = db_session.exec(select(QueuedJob)).all()
    assert len(queued_jobs) == 1
```

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_scheduler_runtime.py ../tests/backend/test_scheduler_daemon.py ../tests/backend/test_worker_runner.py -v`
Expected: FAIL because scheduler runtime, daemon, and callback glue do not exist

- [ ] **Step 3: Implement `SchedulerRuntime` and daemon entrypoint**

```python
class SchedulerRuntime:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def reload_all(self) -> None: ...
    async def trigger_published_job_now(self, published_job_id: UUID, scheduled_at: datetime) -> bool: ...
    async def trigger_auth_policy_now(self, policy_id: UUID, scheduled_at: datetime) -> bool: ...
    async def trigger_crawl_policy_now(self, policy_id: UUID, scheduled_at: datetime) -> bool: ...
```

Implementation notes:
- APScheduler callback 只做重新加载对象与 enqueue
- callback 内保留同分钟去重
- `scheduler_daemon.py` 负责启动 runtime 并阻塞运行

- [ ] **Step 4: Add settings and queue-audit wiring**

Runbook:
- `settings.py` 增加 `scheduler_timezone`、`scheduler_enabled`
- `auth_refresh_job.py` / `crawl_job.py` 保留 `policy_id`、`scheduled_at`、`trigger_source`
- 如需 worker daemon，给 `WorkerRunner` 补 `run_forever(poll_interval_ms)` 之类的轻量入口

- [ ] **Step 5: Run the runtime, daemon, and worker tests**

Run: `cd backend && uv run pytest ../tests/backend/test_scheduler_runtime.py ../tests/backend/test_scheduler_daemon.py ../tests/backend/test_scheduler_service.py ../tests/backend/test_worker_runner.py -v`
Expected: PASS

- [ ] **Step 6: Commit the runtime task**

```bash
git add backend/src/app/runtime/scheduler_runtime.py backend/src/app/runtime/scheduler_daemon.py backend/src/app/config/settings.py backend/src/app/jobs/published_job_trigger.py backend/src/app/jobs/auth_refresh_job.py backend/src/app/jobs/crawl_job.py backend/src/app/workers/runner.py tests/backend/test_scheduler_runtime.py tests/backend/test_scheduler_daemon.py tests/backend/test_scheduler_service.py tests/backend/test_worker_runner.py
git commit -m "feat: add APScheduler runtime and daemon"
```

---

## Task 6: Remove Legacy Scan Path and Update Documentation

**Files:**
- Modify: `backend/src/app/domains/runner_service/scheduler.py`
- Modify: `backend/README.md`
- Modify: `docs/superpowers/specs/2026-04-02-apscheduler-unified-scheduling-design.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write the failing regression/doc expectations**

```python
def test_published_job_service_no_longer_exposes_bulk_cron_scanner():
    from app.domains.runner_service.scheduler import PublishedJobService

    assert not hasattr(PublishedJobService, "trigger_due_jobs")
```

- [ ] **Step 2: Run the regression test to verify it fails**

Run: `cd backend && uv run pytest ../tests/backend/test_scheduler_service.py -v -k bulk_cron_scanner`
Expected: FAIL because the legacy scan entrypoint still exists

- [ ] **Step 3: Remove the legacy scanner and rewrite docs**

Runbook:
- 删除或下沉 `trigger_due_jobs()`
- `backend/README.md` 改为说明 `SchedulerRuntime + APScheduler + scheduler daemon`
- spec 状态改为已进入 plan/implementation 阶段（若本轮需要）
- `CHANGELOG.md` 记录调度实现从自研扫描迁移到 APScheduler runtime

- [ ] **Step 4: Run the focused regression and full backend scheduling suite**

Run: `cd backend && uv run pytest ../tests/backend/test_published_jobs_api.py ../tests/backend/test_runtime_policies_api.py ../tests/backend/test_scheduler_registry.py ../tests/backend/test_scheduler_runtime.py ../tests/backend/test_scheduler_daemon.py ../tests/backend/test_scheduler_service.py ../tests/backend/test_worker_runner.py -v`
Expected: PASS

- [ ] **Step 5: Run the broader backend regression**

Run: `cd backend && uv run pytest ../tests/backend -v`
Expected: PASS or only fail on pre-existing unrelated issues that are documented before merge

- [ ] **Step 6: Commit the cleanup and docs task**

```bash
git add backend/src/app/domains/runner_service/scheduler.py backend/README.md docs/superpowers/specs/2026-04-02-apscheduler-unified-scheduling-design.md CHANGELOG.md
git commit -m "refactor: replace legacy cron scanning with APScheduler runtime"
```

---

## Implementation Notes

- 所有调度 callback 都必须回到 `queued_jobs -> worker` 主链，不允许在 APScheduler callback 中直接跑 Playwright。
- `published_jobs`、`system_auth_policies`、`system_crawl_policies` 继续作为真相源；不要引入 APScheduler job store 双写。
- 保留数据库层面的幂等保护，不要把“不会重复触发”的责任完全交给 APScheduler。
- 第一版只按单实例 scheduler 设计，不提前实现 leader election。
