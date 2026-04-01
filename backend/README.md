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

本地默认数据库和 Redis 参数可参考 [docs/base_info.md](/Users/wangpei/src/singe/Runlet/worktrees/task1-auth-crawl-runtime/docs/base_info.md)。

## 执行迁移

```bash
cd backend
uv run alembic upgrade head
```

## 启动 API

```bash
cd backend
uv run uvicorn app.main:create_app --factory --reload
```

## 运行 Worker

当前阶段还没有独立 CLI，最小运行方式是创建 `WorkerRunner`，注册：

- `AuthRefreshJobHandler`
- `CrawlJobHandler`

然后在循环中调用 `await worker.run_once()`。

这一阶段 `asset_compile` 仍然是受理但未执行的作业类型；worker 遇到它会标记为 `skipped`，并写明原因。

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

## 目录说明

- `src/app/api/`：HTTP 接口与依赖注入
- `src/app/domains/control_plane/`：control plane DTO、仓储、受理服务
- `src/app/domains/auth_service/`：凭据解密、登录刷新、认证态持久化
- `src/app/domains/crawler_service/`：采集编排、提取器契约、事实落库
- `src/app/jobs/`：认证刷新与采集作业 handler
- `src/app/workers/`：最小 FIFO worker
- `src/app/infrastructure/`：数据库、队列和运行时适配
- `alembic/`：迁移环境与版本
