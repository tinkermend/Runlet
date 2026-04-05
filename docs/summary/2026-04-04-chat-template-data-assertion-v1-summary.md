# AI Chat 模板化数据断言 V1 落地总结

**日期：** 2026-04-04  
**对应设计：** `docs/superpowers/specs/2026-04-04-chat-template-based-data-assertion-design.md`  
**对应计划：** `docs/superpowers/plans/2026-04-04-chat-template-data-assertion-v1-plan.md`

---

## 1. 总结定位

本文档总结本轮“AI Chat 模板化数据断言 V1”在后端主链上的实际落地结果，覆盖 `control_plane -> asset_compiler -> runner_service -> run_check worker` 的端到端收口。

本次总结聚焦后端与测试收口，不展开前端交互细节。

---

## 2. 本轮核心目标与完成情况

本轮目标是把“自然语言触发的只读数据断言”从概念能力收敛为可执行、可治理、可调度沉淀的 V1 闭环。已完成：

1. 模板请求契约与模板参数持久化。
2. 候选推荐 API 与排序策略（成功率优先 + 冷启动回退）。
3. V1 模板注册中心与模板驱动 module plan 编译。
4. Runner 增加数据断言模块链执行能力。
5. 只读模板守卫与 `template_params` 透传执行。
6. 主分支集成后的迁移头收敛和鉴权回归修复。

---

## 3. 关键实现内容

### 3.1 候选推荐（Task 3）

- 新增 `POST /api/v1/check-requests:candidates`。
- 排序规则修正为“按候选粒度”应用冷启动：
  - 热启动候选：按 `rank_score`（成功率/别名置信度/recency）排序。
  - 冷启动候选：优先 alias confidence，同分按 recency 打破并列。
- 补齐 service 级回归：冷热混排场景、冷启动同置信度的 recency tie-break。

### 3.2 模板注册与编译（Task 4）

- 新增模板注册中心：
  - `has_data`
  - `no_data`
  - `field_equals_exists`
  - `status_exists`
  - `count_gte`
- `check_templates` 改为可追加模板化标准检查。
- `module_plan_builder` 新增模板链路编译：
  - `action.apply_filter`
  - `action.submit_query`
  - `assert.data_count`
  - `assert.row_exists_by_field`
- 保持已有 `table_render/open_create_modal` 路径兼容，避免历史回归。

### 3.3 Runner 数据断言模块（Task 5）

- 新增 `data_assertion_modules`：
  - 模板占位符解析（`{{slot}}`）
  - 数据计数断言校验
- `module_executor` 增加新模块执行分支。
- `playwright_runtime` 增加对应运行时动作（筛选、提交查询、计数、按字段存在性断言）。
- 补齐 runner 回归：`field_equals_exists/no_data/count_gte/status_exists`。

### 3.4 只读守卫与参数透传（Task 6）

- `control_plane.submit_check_request` 增加只读模板守卫：拒绝非 V1 readonly 模板。
- `run_check_job` 在 precompiled 执行路径读取 `execution_request.template_params`，透传到 `RunnerService.run_page_check(runtime_inputs=...)`。
- 补齐回归：`readonly`、`element_asset_missing`、`template_params`。

---

## 4. 集成收口中的阻塞与处理

本轮在主分支合并后出现两类集成阻塞，均已修复：

1. **Alembic 双 head 阻塞**  
   现象：`0012_exec_req_tpl_params` 与 `0012_identity_pat_auth` 同时为 head，导致 `alembic upgrade head` 失败并连带 schema 测试失败。  
   处理：新增 merge revision `0013_merge_0012_heads` 收敛为单 head。

2. **API 鉴权策略回归**  
   现象：`/api/v1/check-requests` 新增鉴权后，模板相关 API 测试变为 401。  
   处理：模板测试改为显式签发并携带 skills PAT，与最新鉴权语义对齐。

---

## 5. 关键交付物

### 5.1 代表性代码文件

- `backend/src/app/domains/control_plane/recommendation.py`
- `backend/src/app/domains/asset_compiler/template_registry.py`
- `backend/src/app/domains/asset_compiler/module_plan_builder.py`
- `backend/src/app/domains/runner_service/data_assertion_modules.py`
- `backend/src/app/domains/runner_service/module_executor.py`
- `backend/src/app/jobs/run_check_job.py`
- `backend/alembic/versions/0013_merge_0012_heads.py`

### 5.2 代表性测试文件

- `tests/backend/test_check_candidates_api.py`
- `tests/backend/test_control_plane_service.py`
- `tests/backend/test_template_registry.py`
- `tests/backend/test_asset_compiler_service.py`
- `tests/backend/test_runner_service.py`
- `tests/backend/test_run_check_job.py`
- `tests/backend/test_check_requests_api.py`

---

## 6. 验证结果

本轮执行了两阶段核心验证：

1. 功能分支收口回归：`111 passed`。  
2. 合并到 `main` 并修复集成阻塞后回归：`117 passed`。

执行矩阵覆盖：

- `test_check_requests_api.py`
- `test_check_candidates_api.py`
- `test_control_plane_service.py`
- `test_asset_compiler_service.py`
- `test_template_registry.py`
- `test_runner_service.py`
- `test_run_check_job.py`
- `test_initial_schema.py`

---

## 7. 代表性提交

- `8ab88e1` `fix: align candidate ranking semantics and tie-break tests`
- `ab872e5` `feat: add v1 template registry and plan compilation`
- `51fa2f5` `feat: add table list data assertion runtime modules`
- `010a2f6` `feat: enforce readonly templates and pass runtime inputs`
- `a17cd75` `fix: merge alembic heads and align auth-gated api tests`
- `3a07463` `docs: update prompt notes for simulation testing discussion`

---

## 8. 当前结论

本轮后端已具备“模板优先、只读断言、参数化执行、候选推荐、执行沉淀”的 V1 可用闭环，并在主分支完成了集成级问题收敛。

从企业内部 Vue/React 管理平台场景看，该方案已从“菜单点击自动化”推进到“可参数化数据断言自动化”，为后续提升覆盖率（目标 80%）提供了可扩展基础。

---

## 9. 后续建议

1. 为模板 slot 增加更严格的类型校验与 schema 版本演进策略。  
2. 在 runner 层继续增强 table/list 结构化读取能力，减少对文本匹配的依赖。  
3. 对候选推荐引入可观测指标（命中率、误命中率、冷启动命中分布），支持后续排序权重迭代。  
4. 在调度侧增加模板化检查的结果分层看板，形成“模板效果 -> 资产回写 -> 推荐优化”的闭环反馈。
