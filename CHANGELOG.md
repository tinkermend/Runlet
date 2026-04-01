## 2026-04-01

- 初始化 `backend/` 工程骨架，加入 FastAPI app factory、健康检查接口、基础配置和本地运行说明。
- 初始化 `cli/` 工程骨架，提供 `openweb doctor` 诊断命令入口。
- 新增后端启动烟雾测试，验证 `/healthz` 返回基线可用。
- 新增数据库基础设施：`SQLModel` 基础元数据、数据库会话工厂、共享 `AssetStatus` 枚举与分域模型骨架。
- 新增 Alembic 基础配置与初始平台 schema 迁移，覆盖事实层/资产层/执行层 MVP 表（含 `systems`、`page_assets`、`page_checks`、`execution_requests`、`queued_jobs`）。
- 新增初始 schema 冒烟测试，验证迁移后核心表可见。
- 对齐 foundation 计划中的核心字段语义，修正 `systems`、`page_assets`、`execution_requests`、`queued_jobs` 的列定义与初始迁移。
- 补充 schema 与 `SQLModel` metadata 一致性校验，并将数据库会话工厂调整为复用默认异步 engine。
- 新增 control-plane DTO、仓储、服务和 SQL 队列派发抽象，支持检查请求归一化、执行计划入库与 `run_check` 作业受理。
- 新增 control-plane 服务测试夹具与异步服务测试，覆盖预编译命中与实时回退两条基础路径。
- 修正 control-plane 作业受理的一致性与解析策略，改为单事务提交，并优先选择 `READY` 且高置信度的资产命中结果。
- 对齐 check-request API 的生产依赖 wiring，并补充状态查询对真实 `QueuedJob.status` 与缺失请求 `404` 的覆盖。
- 新增 check-request control-plane API，暴露检查请求创建与状态查询端点，并补充对应的 FastAPI 集成测试。
- 新增 page-check run 与 page-asset check listing API，复用 control-plane service/repository 受理直跑任务与 READY 资产下的检查列表查询。
- 修正 page-asset checks 列表语义：非 `READY` 资产也返回已持久化的 `page_checks`，并显式暴露当前资产状态。
- 新增认证刷新、采集触发、快照资产编译三个 control-plane 受理 API，并补充目标不存在 `404` 与作业入队测试覆盖。
- 收敛后端测试 seed helpers 到共享 `conftest.py`，补充 `seeded_system`、`seeded_page_asset`、`seeded_page_check`、`seeded_snapshot`、`accepted_request` 等复用夹具，并完善本地开发与环境变量说明。
