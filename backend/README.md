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
- `SESSION_SECRET`：Web 控制台 session 签名密钥（必须在环境中配置为强随机值）
- `SESSION_TTL_HOURS`：Web 控制台 session 过期小时数
- `PASSWORD_PEPPER`：可选密码 pepper（为空表示不启用）
- `PAT_MAX_TTL_DAYS`：PAT 最大可签发天数上限
- `PAT_ALLOWED_TTL_DAYS`：允许签发的 PAT 天数白名单（如 `3,7`）

本地默认数据库和 Redis 参数可参考仓库内的 `docs/base_info.md`。

## 认证模型（V1）

- Web 管理平台：使用 `/api/console/auth/login` 写入 `console_session` cookie，并通过 `/api/console/auth/me` 校验登录态。
- Skills 对话调用：使用 `Authorization: Bearer rpat_xxx`（用户在 Web 管理平台创建的临时 PAT）。
- 后端统一授权：按 `channel + action + system` 判权，`skills` 渠道禁止手动触发 crawl。

## Web 系统接入 YAML 示例

`openweb web-system add/remove` 可直接参考以下示例清单：

- `docs/examples/web-system-manifest.example.yaml`

其中 `credential.username/password` 可以写明文，真正入库前会使用 `backend/.env` 中的 `credential_crypto_secret` 加密。

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

当前已经提供正式 worker daemon 入口：

```bash
cd backend
./.venv/bin/runlet-worker
```

或使用你本地的工具链包装：

```bash
cd backend
uv run runlet-worker
```

如果 worker 未启动，`auth_refresh`、`crawl`、`asset_compile`、`run_check` 任务只会停留在 `queued_jobs.status=accepted`，不会被实际消费。

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

### 双轨受理语义

`check_request` 当前只有两条正式后端轨道：

- `precompiled`：命中 `page_check` 后直接按现有 `module_plan` 执行
- `realtime_probe`：仅在页面或菜单未命中时触发页面级受控探测

边界约束如下：

- 页面或菜单未命中：允许走 `realtime_probe`
- 页面已命中但元素资产缺失：直接返回 `409 element asset is missing`
- `realtime_probe` 仍由服务端注入认证并回写正式执行记录，不允许变成自由脚本执行旁路

### 查询统一结果

```bash
curl "http://127.0.0.1:8000/api/v1/check-requests/<request-id>/result"
```

返回结构会统一汇总：

- `request_id/plan_id/page_check_id/execution_track`
- `execution_summary`：最新一次执行的 `status/auth_status/duration_ms/failure_category/final_url/page_title/asset_version`
- `artifacts`：当前执行对应的 `module_execution`、`screenshot` 等工件
- `needs_recrawl/needs_recompile`：供上层决定是否补采集或补编译

其中：

- `execution_track` 对外只暴露 `precompiled` 或 `realtime_probe`
- `artifacts[].artifact_uri` 可用于获取截图等外部产物路径
- `realtime_probe` 成功后，如已恢复到现有页面资产，会在结果中给出后续补编译提示

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

### 从成功检查直接发布

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/check-requests/<request-id>:publish" \
  -H "content-type: application/json" \
  -d '{
    "schedule_expr":"0 */2 * * *",
    "trigger_source":"platform",
    "enabled":true
  }'
```

该入口只允许晋升“最新一次执行成功”的检查请求，并遵守以下规则：

- 只接受存在 `page_check` 的成功执行上下文
- 优先复用已经绑定到该 `execution_plan` 的 `published` 模式 `script_render`
- 如果还没有发布脚本，则按当前 `page_check` 现状即时渲染一份 `published` 脚本再创建 `published_job`

也就是说，发布动作仍然建立在 `page_check + asset_version + runtime_policy` 上，脚本文本只是派生产物，不是调度真相。

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
- `SchedulerRegistry`（`src/app/domains/control_plane/scheduler_registry.py`）：数据库真相到 APScheduler job 的映射层，负责 `published_job`、`auth_policy`、`crawl_policy` 的 upsert/remove；daemon 侧使用 fresh session 周期重载，避免长生命周期 session 缓存旧状态。
- `scheduler_daemon`（`src/app/runtime/scheduler_daemon.py`）：常驻进程入口，负责托管 `SchedulerRuntime` 生命周期，并按 `scheduler_reload_interval_seconds` 周期从数据库收敛最新调度对象。

当前触发链路：

1. `control_plane` 写入 `published_jobs` 或 `runtime_policies` 后最佳努力调用 `SchedulerRegistry` 注册/更新 APScheduler 触发器；若镜像同步失败，请求仍以数据库提交为准返回成功。
2. APScheduler 到点 fire，`SchedulerRuntime` 监听调度事件并按 job kind 回调。
3. `published_job` 回调重入 `PublishedJobService.trigger_scheduled_job(...)`，创建 `job_run` 并入队 `run_check`。
4. `auth_policy`/`crawl_policy` 回调分别入队 `auth_refresh`/`crawl`，并写入 `policy_id`、`trigger_source=scheduler`、`scheduled_at` 审计字段。

### 启动 scheduler daemon

```bash
cd backend
uv run runlet-scheduler
```

该命令会构建独立的 `SchedulerRuntime` 进程，并定期执行 `reload_all()`，因此即使 API 进程内的热同步镜像失败或与 daemon 不在同一进程，运行中的调度器也会从数据库真相源收敛到最新状态。

### 启动 worker daemon

```bash
cd backend
uv run runlet-worker
```

该命令会构建正式 `WorkerRunner` 进程，接线 `auth_refresh`、`crawl`、`asset_compile`、`run_check` 四类 handler。`run_check` 现在默认使用 `PlaywrightRunnerRuntime`，由服务端注入认证态并消费 `module_plan`，不会直接把脚本文本当作唯一执行真相。

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
  ../tests/backend/test_check_results_api.py \
  ../tests/backend/test_runner_service.py \
  ../tests/backend/test_run_check_job.py \
  ../tests/backend/test_script_renderer.py \
  ../tests/backend/test_publish_from_execution_api.py \
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
