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
