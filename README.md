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

## 文档入口

设计与计划文档建议按下面顺序阅读：

### 设计文档

- `docs/superpowers/specs/2026-04-01-ai-playwright-execution-platform-design.md`
- `docs/superpowers/specs/2026-04-01-ai-playwright-execution-platform-architecture.md`
- `docs/superpowers/specs/2026-04-01-ai-playwright-execution-platform-data-model.md`
- `docs/superpowers/specs/2026-04-01-ai-playwright-execution-platform-api-contracts.md`

### 实施计划

- `docs/superpowers/plans/2026-04-01-ai-playwright-platform-foundation.md`
- `docs/superpowers/plans/2026-04-01-ai-playwright-platform-auth-crawl.md`
- `docs/superpowers/plans/2026-04-01-ai-playwright-platform-asset-compiler.md`
- `docs/superpowers/plans/2026-04-01-ai-playwright-platform-runner-scheduling.md`

## 推荐实施顺序

不要并行乱做，按阶段推进：

1. foundation
   - 后端骨架
   - 核心数据模型
   - control-plane API
   - 作业受理基线
2. auth + crawl
   - 认证刷新
   - crawl snapshots
   - 菜单、页面、元素事实入库
3. asset compiler + drift
   - 页面资产
   - 标准检查项
   - 模块计划
   - 漂移检测
4. runner + script render + scheduling
   - 受控执行
   - Playwright 脚本渲染
   - published jobs
   - scheduler

## 推荐目录

```text
project-root/
  AGENTS.md
  README.md
  CHANGELOG.md

  backend/
    pyproject.toml
    src/
      app/
      domains/
      infrastructure/
      jobs/
      workers/

  cli/
  mcp_server/
  front/
  skills/
  docs/
  docker/
  tests/
```

## 子域边界

- `control_plane`
  - 请求归一化
  - 执行路径选择
  - 任务编排
- `auth_service`
  - 认证刷新
  - 认证校验
  - 服务端注入认证
- `crawler_service`
  - 菜单、页面、元素采集
  - runtime 提取与 DOM fallback
- `asset_compiler`
  - 页面资产
  - 标准检查
  - 模块计划
  - 漂移状态
- `runner_service`
  - 执行模块计划
  - 渲染脚本
  - 记录执行结果

## 技术栈

- Backend: FastAPI + Pydantic v2 + SQLAlchemy / SQLModel
- DB: PostgreSQL
- Cache / Lock: Redis
- Browser Runtime: Playwright Python
- Scheduler: APScheduler
- Worker: Python worker process
- CLI: Typer
- MCP: FastMCP
- Front: React + Vite
- Test: pytest

## 开发原则

- 先实现资产模型和控制面，再做复杂浏览器能力
- 先做 deterministic path，再补 runtime fallback
- 不把自由脚本文本作为系统唯一真相
- 不让 CLI / MCP / Skills 绕过后端执行正式检查
- 不依赖动态 ID 作为定位策略

## 当前状态建议

如果这是一个新仓库的初始 README，建议下一步优先完成：

1. 初始化 `backend/` 工程骨架
2. 建立数据库模型与迁移
3. 搭建第一个 control-plane API
4. 让第一份 foundation plan 跑通
