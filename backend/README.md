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

## 目录说明

- `src/app/api/`：HTTP 接口与依赖注入
- `src/app/domains/control_plane/`：control plane DTO、仓储、受理服务
- `src/app/domains/auth_service/`：凭据解密、登录刷新、认证态持久化
- `src/app/domains/crawler_service/`：采集编排、提取器契约、事实落库
- `src/app/domains/asset_compiler/`：事实转资产、标准检查、模块计划、漂移计算
- `src/app/jobs/`：认证刷新、采集、资产编译作业 handler
- `src/app/workers/`：最小 FIFO worker
- `src/app/infrastructure/`：数据库、队列和运行时适配
- `alembic/`：迁移环境与版本
