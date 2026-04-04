# AI Playwright Execution Platform

一个面向 AI 对话、Playwright 执行、脚本发布与调度治理的执行平台。

## 项目定位

本项目的目标不是单纯采集页面结构，也不是单纯生成一次性 Playwright 脚本，而是把以下能力统一到一个平台中：

- 多系统认证管理与登录态治理
- Vue / React Web 系统菜单、页面、元素采集
- 页面级执行资产编译
- 统一控制面的检查执行
- Playwright 脚本渲染与发布
- 定时调度与触发调度
- 漂移检测与资产生命周期管理

核心原则：

- 检查资产是主模型，脚本是派生产物
- 正式执行统一走 control plane
- 认证注入统一由服务端执行
- 页面级资产是主运行单元，模块计划是执行底座

## 技术栈

- Backend: FastAPI + Pydantic v2 + SQLModel + UV
- DB: PostgreSQL
- Cache / Lock: Redis
- Browser Runtime: Playwright Python
- Scheduler: APScheduler
- Worker: Python worker process
- CLI: Typer
- MCP: FastMCP
- Front: React + Vite
- Test: pytest

## 本地运行总览

默认本地地址：

- Backend API: `http://127.0.0.1:8000`
- Front: `http://127.0.0.1:5173`


## Backend 启动、停止与配置

### 1) 初始化与迁移

```bash
cd backend

uv sync --dev
cp .env.example .env
uv run alembic upgrade head
```

### 2) 启动

启动 API：

```bash
cd backend

source .venv/bin/active
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

启动 Worker（可选，但队列任务消费依赖它）：

```bash
cd backend
uv run runlet-worker
```

启动 Scheduler（可选，定时任务依赖它）：

```bash
cd backend
uv run runlet-scheduler
```

### 3) 停止

- 前台运行：在对应终端按 `Ctrl + C`
- 后台运行（按进程名）：

```bash
pkill -f "uvicorn app.main:create_app" || true
pkill -f "runlet-worker" || true
pkill -f "runlet-scheduler" || true
```

### 4) 关键配置项（`backend/.env`）

必需项（`backend/.env.example` 已给默认值）：

- `DATABASE_URL`: 后端 API / Worker / Scheduler 共享数据库连接
- `REDIS_URL`: control plane 队列链路

常用可调项：

- `LOG_LEVEL`: 日志级别
- `WORKER_POLL_INTERVAL_MS`: worker 轮询间隔（毫秒）
- `SCHEDULER_RELOAD_INTERVAL_SECONDS`: scheduler 重载数据库调度配置的周期（秒）
- `CONSOLE_USERNAME` / `CONSOLE_PASSWORD`: Console 登录账号密码（默认 `admin/admin`）

## Front 启动、停止与配置

### 1) 初始化

```bash
cd front
npm install
```

### 2) 启动

```bash
cd front
npm run dev -- --host 127.0.0.1 --port 5173
```

### 3) 停止

- 前台运行：当前终端 `Ctrl + C`
- 后台运行：`pkill -f "vite" || true`

### 4) 前端联调配置说明

- 本地开发代理配置在 [front/vite.config.ts](/Users/wangpei/src/singe/Runlet/front/vite.config.ts)
- `/api` 默认代理到 `http://localhost:8000`
- 若后端不在 `8000`，请同步修改 `vite.config.ts` 的 `server.proxy["/api"].target`

## CLI 启动、停止与配置

CLI 是命令行工具，不是常驻服务，执行完命令即退出。

### 1) 初始化

```bash
cd cli
uv sync --dev
```

### 2) 运行

基础检查：

```bash
cd cli
uv run openweb doctor
```

接入系统（示例）：

```bash
cd cli
set -a; source ../backend/.env; set +a
uv run openweb web-system add --file ../docs/examples/web-system-manifest.example.yaml
```

删除系统（示例）：

```bash
cd cli
set -a; source ../backend/.env; set +a
uv run openweb web-system remove --system-code <system-code>
```

### 3) 停止

- 正常命令会自动结束
- 若命令阻塞，按 `Ctrl + C` 中断即可
