# AI Playwright 执行平台设计总览

**日期：** 2026-04-01  
**作者：** Codex  
**状态：** Draft

---

## 1. 文档定位

本文档是 foundation 阶段在当前仓库内保留的总览规格，描述 AI Playwright 执行平台的目标、边界和实施顺序。

平台按以下原则组织：

- 检查资产是主模型
- Playwright 脚本是派生产物
- 正式执行统一走 control plane
- 认证注入由服务端统一处理

---

## 2. 当前 foundation 交付范围

本阶段已经落地 backend MVP 基座，包含：

- FastAPI 后端骨架、基础配置和本地开发入口
- 初始数据库迁移与核心事实层/资产层/执行层/作业层表结构
- control-plane 检查请求 API 与状态查询
- page-check 直跑与 page-asset checks 查询
- 认证刷新、采集触发、快照资产编译的作业受理 API
- 后端共享测试夹具与最小本地启动文档

---

## 3. 架构边界

系统按五个核心子域演进：

- `control_plane`
- `auth_service`
- `crawler_service`
- `asset_compiler`
- `runner_service`

约束如下：

- 只有 `control_plane` 可以跨域编排
- `auth_service` 不负责页面识别和检查选择
- `crawler_service` 只负责采集事实，不负责最终执行
- `asset_compiler` 只负责把事实转换成资产，不负责直接执行
- `runner_service` 只负责执行被批准的计划，不负责解释自然语言

---

## 4. 实施顺序建议

建议按以下顺序继续推进：

1. 先完成 foundation 计划，稳定 backend MVP、核心 schema 与 control-plane API 基线
2. 再推进 auth/crawler follow-on plan，补齐认证刷新执行链路与 crawl snapshot ingestion
3. 然后推进 asset compiler follow-on plan，补齐页面资产编译与 drift classification
4. 最后推进 runner/script/schedule follow-on plan，补齐正式执行、脚本渲染、发布与调度能力

对应的 follow-on 边界：

- 认证刷新与采集执行不在 foundation 内实现，只保留触发入口
- 资产编译在 foundation 内只受理作业，不实现完整编译与漂移治理
- 运行器、脚本渲染、已发布脚本调度属于最后一阶段，不在 foundation 内展开

---

## 5. 总结

当前仓库已经具备“可启动、可迁移、可入库、可受理控制面作业”的 backend foundation，可作为后续 auth/crawler、asset compiler、runner/script/schedule 三个计划的承接底座。
