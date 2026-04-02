# AI Playwright Platform Backend

## 初始化

```bash
cd backend
uv sync --dev
cp .env.example .env
```

## 必需环境变量

`backend/.env.example` 中的变量同时供 API 进程和本地 worker 使用：

- `APP_NAME`：服务名称
- `APP_ENV`：运行环境标识
- `LOG_LEVEL`：日志级别
- `DATABASE_URL`：API/worker 共用的异步数据库连接串
- `REDIS_URL`：control plane 受理队列使用的 Redis 地址

本地默认数据库和 Redis 参数可参考仓库内的 `docs/base_info.md`。

## 执行迁移

```bash
cd backend
uv run alembic upgrade head
```

默认会读取 `backend/.env` 中的 `DATABASE_URL` 作为迁移目标，并自动把运行时 async URL 转换成 Alembic 所需的 sync URL。
只有在测试或显式覆盖 `sqlalchemy.url` 时，才会改用外部指定的数据库连接。

## 启动 API

```bash
cd backend
uv run uvicorn app.main:create_app --factory --reload
```

## 运行 Worker

当前阶段还没有独立 CLI，最小运行方式是创建 `WorkerRunner`，注册：

- `AuthRefreshJobHandler`
- `CrawlJobHandler`
- `AssetCompileJobHandler`
- `RunCheckJobHandler`

然后在循环中调用 `await worker.run_once()`。

## 触发认证刷新

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/systems/<system-id>/auth:refresh"
```

返回 `202 Accepted`，并包含真实的 `job_id`。该 `job_id` 对应队列中的认证刷新任务。

## 触发采集

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/systems/<system-id>/crawl" \
  -H "content-type: application/json" \
  -d '{"crawl_scope":"full","framework_hint":"auto","max_pages":50}'
```

同样返回 `202 Accepted` 和真实的 `job_id`。

## Crawl 后的 Compile Handoff

当前链路不是由 API 直接返回 `snapshot_id`。实际流程是：

1. API 受理 crawl 请求并返回 crawl `job_id`
2. worker 执行 crawl job，持久化新的 `crawl_snapshot`、`pages`、`menu_nodes`、`page_elements`
3. crawl 成功后，worker 自动追加一个 `asset_compile` 队列任务
4. 该 compile job 的 payload 中会携带新生成的 `snapshot_id`

也就是说，compile handoff 发生在 worker 内部的 job 链路中，而不是由 crawl 受理接口同步返回。

## 触发资产编译

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/snapshots/<snapshot-id>/compile-assets" \
  -H "content-type: application/json" \
  -d '{"compile_scope":"impacted_pages_only"}'
```

返回 `202 Accepted`，包含：

- `snapshot_id`
- `job_type=asset_compile`
- `job_id`

## 资产编译与漂移说明

资产编译器会把 `crawl_snapshots/pages/menu_nodes/page_elements` 这些事实层数据转换为以下资产层对象：

- `page_assets`：页面资产主记录，默认由 `system_code + route_path` 生成 `asset_key`
- `page_checks`：标准检查定义
- `module_plans`：运行器优先消费的确定性步骤计划
- `asset_snapshots`：每次编译生成的结构快照与 diff 分数
- `intent_aliases`：初始意图别名，用于 `intent_aliases -> page_assets -> page_checks` 命中

当前内置的标准检查至少包含：

- `page_open`
- `table_render`
- `open_create_modal`

漂移状态说明：

- `safe`：结构变化较小，可继续作为默认命中资产
- `suspect`：结构有中等变化，需要关注但仍保留资产结果
- `stale`：结构变化较大，表示资产明显老化

编译结果可从以下位置查看：

- `queued_jobs.result_payload`：一次 compile job 的汇总结果
- `page_assets.status`：当前页面资产状态
- `page_checks.module_plan_id`：检查与模块计划的绑定
- `asset_snapshots`：每次编译的指纹与 diff 记录

## run_check 执行链路

`run_check` 是平台内部执行 `page_check` 的正式作业类型，默认围绕 `page_check + module_plan + runtime_policy` 运行，而不是直接执行一段孤立脚本文本。当前链路如下：

1. control plane 受理检查请求，优先通过 `intent_aliases -> page_assets -> page_checks` 命中检查，并创建 `execution_request`、`execution_plan`、`queued_job`
2. worker 取到 `run_check` 后，调用 `RunnerService.run_page_check()`
3. runner service 解析 `page_check/module_plan`，读取有效认证态，并在服务端注入认证后按步骤执行模块计划
4. 执行结果写回 `execution_runs`、`execution_artifacts`，队列状态与 `queued_jobs.result_payload` 同步更新

当前 `RunCheckJobHandler` 也会在调度场景下把 `published_job_id`、`job_run_id`、`script_render_id`、`asset_version`、`runtime_policy`、`schedule_expr` 等上下文写入 `result_payload`，便于后续审计。

## 渲染 Playwright 脚本

渲染接口：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/page-checks/<page-check-id>:render-script" \
  -H "content-type: application/json" \
  -d '{"render_mode":"published"}'
```

接口会：

1. 解析 `page_check -> module_plan`
2. 生成稳定的 Playwright Python 脚本文本
3. 持久化一条 `script_renders` 记录

当前支持：

- `render_mode=runtime`
- `render_mode=published`

`script_renders.render_metadata` 会保存 `asset_version`、`module_plan_id`、`plan_version`、`runtime_policy`、`auth_policy`、`script_sha256`、`script_path` 等元数据。认证策略始终保持为“由平台服务端注入”，不会把完整 `storage_state` 作为上层通用输出。

## 发布任务与调度

### 创建发布任务

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/published-jobs" \
  -H "content-type: application/json" \
  -d '{
    "script_render_id":"<script-render-id>",
    "page_check_id":"<page-check-id>",
    "schedule_type":"cron",
    "schedule_expr":"0 */2 * * *",
    "trigger_source":"platform",
    "enabled":true
  }'
```

创建时会绑定：

- `page_check_id`
- `script_render_id`
- `asset_version`
- `runtime_policy`
- `schedule_expr`

平台的主调度对象仍然是 `published_job/page_check/asset_version/runtime_policy` 组合，而不是单独调度脚本文本。

### 手动触发发布任务

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/published-jobs/<published-job-id>:trigger"
```

接口会创建：

- `job_runs`
- 对应的 `run_check` 队列任务

当前队列 payload 会保留 `published_job_id`、`job_run_id`、`queued_job_id`、`script_render_id`、`asset_version`、`runtime_policy`、`schedule_expr`、`trigger_source`、`scheduled_at` 等审计快照。

### 查询发布任务运行记录

```bash
curl "http://127.0.0.1:8000/api/v1/published-jobs/<published-job-id>/runs"
```

可查看该发布任务关联的 `job_runs` 列表及其 `execution_run_id/run_status/started_at/finished_at`。

### 统一调度运行时结构

当前调度运行时由以下组件组成：

- `SchedulerRuntime`（`src/app/runtime/scheduler_runtime.py`）：APScheduler 的进程内宿主，负责启动/停止、重载注册项，并在 job fire 后回调到平台 enqueue 边界。
- `SchedulerRegistry`（`src/app/domains/control_plane/scheduler_registry.py`）：数据库真相到 APScheduler job 的映射层，负责 `published_job`、`auth_policy`、`crawl_policy` 的 upsert/remove。
- `scheduler_daemon`（`src/app/runtime/scheduler_daemon.py`）：常驻进程入口，负责托管 `SchedulerRuntime` 生命周期。

当前触发链路：

1. `control_plane` 写入 `published_jobs` 或 `runtime_policies` 后调用 `SchedulerRegistry` 注册/更新 APScheduler 触发器。
2. APScheduler 到点 fire，`SchedulerRuntime` 监听调度事件并按 job kind 回调。
3. `published_job` 回调重入 `PublishedJobService.trigger_scheduled_job(...)`，创建 `job_run` 并入队 `run_check`。
4. `auth_policy`/`crawl_policy` 回调分别入队 `auth_refresh`/`crawl`，并写入 `policy_id`、`trigger_source=scheduler`、`scheduled_at` 审计字段。

### APScheduler 回调触发

当前 runner 域的调度触发边界是 `PublishedJobService.trigger_scheduled_job(published_job_id, scheduled_at)`。该入口由 APScheduler job callback 按 `published_job_id + scheduled_at` 调用：

1. 对目标 `published_job` 加锁并校验 `state=active`
2. 用传入的 `scheduled_at` 对 `schedule_expr` 做二次匹配，防止旧触发器在计划变更后继续入队
3. 校验同一分钟是否已触发，避免重复创建 `job_run`
4. 通过 `PublishedJobTrigger` 创建 `job_run` 并投递 `run_check`

也就是说，调度回调的结果仍然回到平台内部的 `run_check` 执行链，而不是直接在调度器里执行 Playwright 脚本。

## 运行测试

```bash
cd backend
uv run pytest ../tests/backend -v
```

auth/crawl 相关测试集：

```bash
cd backend
uv run pytest \
  ../tests/backend/test_auth_service.py \
  ../tests/backend/test_auth_job.py \
  ../tests/backend/test_crawler_service.py \
  ../tests/backend/test_crawl_job.py \
  ../tests/backend/test_worker_runner.py \
  ../tests/backend/test_job_submission_api.py -v
```

asset compiler 相关测试集：

```bash
cd backend
uv run pytest \
  ../tests/backend/test_asset_fingerprints.py \
  ../tests/backend/test_asset_compiler_service.py \
  ../tests/backend/test_asset_compile_job.py \
  ../tests/backend/test_assets_api.py -v
```

runner/render/scheduling 相关测试集：

```bash
cd backend
uv run pytest \
  ../tests/backend/test_runner_service.py \
  ../tests/backend/test_run_check_job.py \
  ../tests/backend/test_script_renderer.py \
  ../tests/backend/test_published_jobs_api.py \
  ../tests/backend/test_scheduler_service.py -v
```

## 目录说明

- `src/app/api/`：HTTP 接口与依赖注入
- `src/app/domains/control_plane/`：control plane DTO、仓储、受理服务
- `src/app/domains/auth_service/`：凭据解密、登录刷新、认证态持久化
- `src/app/domains/crawler_service/`：采集编排、提取器契约、事实落库
- `src/app/domains/asset_compiler/`：事实转资产、标准检查、模块计划、漂移计算
- `src/app/jobs/`：认证刷新、采集、资产编译、run_check、published job trigger 作业逻辑
- `src/app/workers/`：最小 FIFO worker
- `src/app/infrastructure/`：数据库、队列和运行时适配
- `alembic/`：迁移环境与版本
