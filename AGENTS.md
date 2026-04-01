# AGENTS.md

## 项目定位

这是一个面向 AI 对话、Playwright 执行、脚本发布与调度治理的执行平台。

请始终记住：

- 检查资产是主模型
- Playwright 脚本是派生产物
- 正式执行统一走 control plane
- 认证注入必须由服务端统一处理

## 架构约束

系统按以下五个核心子域组织：

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

## 工程目录约束

- `backend/domains/*` 承载核心业务逻辑
- `cli` 只做命令入口，不复制领域逻辑
- `mcp_server` 只做轻量查询或受控转调，不直接实现正式执行逻辑
- `skills` 只做编排，不直接访问数据库或认证信息
- `tests` 放跨模块测试和端到端测试

## 数据模型约束

系统至少分四层模型：

1. 事实层
2. 资产层
3. 执行层
4. 调度与脚本层

必须遵守：

- 运行时默认从 `intent_aliases -> page_assets -> page_checks` 命中
- 不从 `page_elements` 开始直接推理执行
- 调度对象优先是 `page_check` 或 `published_job`
- `script_renders` 是脚本产物记录，不是系统唯一真相

## Playwright 约束

- 菜单和元素采集必须优先使用现代稳定定位策略
- 不要依赖动态 ID
- 优先使用角色、文本、语义属性、结构化定位
- 运行器执行时必须优先消费 `module_plan`
- 只有在必要时才渲染完整 Playwright 脚本

## 认证与安全约束

- 所有正式执行必须由服务端注入认证
- 不允许把完整 `storage_state` 作为通用上层输出
- 已发布脚本必须绑定资产版本和认证策略
- 不允许本地浏览器登录态复用成为正式执行主链

## 调度约束

系统支持两种调度模式：

- 平台内资产调度
- 已发布脚本调度

但默认主模式始终是：

- 调度 `page_check`
- 调度 `asset_version`
- 调度 `runtime_policy`

不是直接调度一段孤立脚本文本。

## 文档与计划约束

- 任何重要架构变更必须先更新 `docs/superpowers/specs/`
- 任何实施拆解必须更新 `docs/superpowers/plans/`
- 开发顺序默认遵循四份计划：
  - foundation
  - auth + crawl
  - asset compiler + drift
  - runner + script render + scheduling

## 测试与变更约束

- 每次开发完成必须补充或更新测试
- 每次变更都要更新 `CHANGELOG.md`
- 没有验证结果，不要声称“已完成”或“已修复”

## 实施风格

- 优先小步提交
- 优先 deterministic 实现
- 优先清晰边界，不做跨域大杂烩
- 不要为未来假想需求过度设计
- 不要跳过基础模型直接写复杂浏览器执行
