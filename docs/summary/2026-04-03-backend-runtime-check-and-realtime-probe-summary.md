# 后端检查执行与受控实时探测计划总结

**日期：** 2026-04-03  
**对应设计：** `docs/superpowers/specs/2026-04-03-backend-runtime-check-and-realtime-probe-design.md`  
**对应计划：** `docs/superpowers/plans/2026-04-03-backend-runtime-check-and-realtime-probe-plan.md`

---

## 1. 总结定位

本文档用于总结“后端检查执行与受控实时探测计划”的实际落地结果，面向后续继续维护该平台的开发者与架构设计人员。

本次总结只覆盖后端，不讨论 CLI、Skills、MCP 和前端实现细节。

---

## 2. 本次计划解决了什么

本轮工作的核心目标，是把原本“概念上区分 `precompiled` / `realtime`，但运行闭环并不完整”的后端，补成一个真正可执行、可返回结果、可截图、可调度固化的最小闭环。

落地后，后端已经具备以下能力：

1. 结构化检查请求可以稳定分流到两条正式轨道：
   - `precompiled`
   - `realtime_probe`
2. 页面或菜单未命中时，不再直接让链路失败，而是允许进入页面级受控探测。
3. 页面已命中但元素资产缺失时，保持快速失败，不退化为自由脚本推理。
4. `runner_service` 已经能够返回截图、最终 URL、页面标题、失败分类和结构化 artifacts。
5. `check_request` 已具备统一结果查询接口，结果模型足以服务上层消费。
6. 一次成功执行可以直接晋升为 `published_job`，进入平台调度链路。

---

## 3. 本次计划的关键架构结论

本轮落地继续坚持并验证了以下架构原则：

- 自然语言解析仍由 `skill` 负责，后端只接受结构化参数。
- 检查资产仍是主模型，运行时默认从 `intent_aliases -> page_assets -> page_checks` 命中。
- `realtime_probe` 只作为页面级受控降级轨道存在，不扩展成元素级自由执行器。
- `script_renderer` 仍是派生产物层，不是正式执行真相。
- 正式执行、认证注入、结果持久化和调度晋升仍统一由后端控制面与运行链路负责。

这意味着系统没有走向“实时生成 Playwright 脚本并直接执行”的模式，而是继续收敛在“资产优先、必要时页面级降级”的平台形态上。

---

## 4. 实际落地内容

### 4.1 双轨受理与失败边界

已完成：

- `control_plane` 根据命中情况选择 `precompiled` 或 `realtime_probe`
- 页面或菜单未命中时进入 `realtime_probe`
- 页面已命中但元素资产缺失时返回 `409 element asset is missing`
- 对外轨道命名统一收敛为 `precompiled` / `realtime_probe`

这部分解决了原先“实时轨道只是概念，worker 会直接跳过”的断点。

### 4.2 运行器升级为完整受控执行器

已完成：

- 增加失败分类常量与结果契约
- 执行结果可返回 `final_url`、`page_title`
- 执行过程中可持久化截图 artifact
- 运行结果与 artifacts 已能被稳定查询和审计
- `open_create_modal` 等模块执行能力得到补齐

这部分使 `runner_service` 从“只跑几步模块”的轻量执行器，演进为“可执行、可截图、可解释”的正式后端执行器。

### 4.3 `realtime_probe` 正式可执行

已完成：

- worker 不再跳过 `realtime_probe`
- `runner_service` 新增页面级 probe 执行能力
- `probe_plan` 已作为明确的页面级计划对象建模
- realtime probe 的成功/失败都会回写正式执行记录

这部分解决了实时降级轨道“受理存在、执行不存在”的历史问题。

### 4.4 统一结果查询与反馈回写

已完成：

- 新增 `GET /api/v1/check-requests/{request_id}/result`
- 结果中统一输出：
  - 执行摘要
  - artifacts
  - `needs_recrawl`
  - `needs_recompile`
- `realtime_probe` 成功后可把 route / alias 反馈回资产命中层
- 反馈回写已绑定到“真正成功且仍为最新的一次 execution_run”

这部分把“运行结果”从队列内部状态，提升为了稳定的上层消费对象。

### 4.5 从成功执行晋升为调度对象

已完成：

- 新增 `POST /api/v1/check-requests/{request_id}:publish`
- 仅允许最新一次成功执行晋升为发布对象
- 晋升时优先复用当前执行上下文已经存在的 `published` 脚本产物
- 如无现成 `script_render`，则按 `page_check` 即时渲染后创建 `published_job`

这部分把“执行一次”与“固化为平台调度对象”真正串成了一条产品链路。

---

## 5. 本次计划没有做什么

本轮明确没有做以下内容：

- 不在后端解析自然语言
- 不允许元素级缺失时走自由 Playwright 兜底
- 不把自由脚本文本升级为系统唯一真相
- 不让 `runner_service` 承担跨域编排职责
- 不把 `realtime_probe` 扩展成通用页面采集器或 crawler 替代品

这些边界是刻意保留的，不是遗漏。

---

## 6. 关键交付物

本次计划新增或强化的关键能力主要落在以下对象与接口上：

- `check_request` 双轨受理
- `runner_service` 截图与页面上下文输出
- `run_check` worker 对 `realtime_probe` 的正式执行
- `check_request result` 统一结果查询
- `realtime_probe` 成功反馈回写
- `publish-from-execution` 发布入口

关键接口：

- `GET /api/v1/check-requests/{request_id}`
- `GET /api/v1/check-requests/{request_id}/result`
- `POST /api/v1/check-requests/{request_id}:publish`

---

## 7. 验证结果

本轮工作在实现完成后，实际执行了两类关键验证：

### 7.1 目标回归集

执行命令：

```bash
cd /Users/wangpei/src/singe/Runlet/backend
uv run pytest ../tests/backend/test_control_plane_service.py ../tests/backend/test_check_requests_api.py ../tests/backend/test_check_results_api.py ../tests/backend/test_runner_service.py ../tests/backend/test_run_check_job.py ../tests/backend/test_realtime_probe_flow.py ../tests/backend/test_publish_from_execution_api.py ../tests/backend/test_published_jobs_api.py -v
```

结果：

- `60 passed`

### 7.2 完整 backend 回归

执行命令：

```bash
cd /Users/wangpei/src/singe/Runlet/backend
uv run pytest ../tests/backend -v
```

结果：

- `179 passed`

因此，本次计划对应的后端开发、测试与验证已经完成收口。

---

## 8. 代表性提交

本次计划的代表性提交包括：

- `98d583c` `feat: add realtime probe track selection`
- `af01988` `feat: add runner failure categories and result schema`
- `4e11f69` `feat: extend runner runtime for screenshots and probe context`
- `513e473` `feat: execute realtime probe jobs in worker`
- `def6e80` `feat: add unified check result view`
- `9018ada` `feat: persist realtime probe feedback hints`
- `f811d17` `fix: bind probe feedback to execution runs`
- `fa0dfca` `feat: publish successful checks into scheduled jobs`
- `78b1221` `docs: document runtime probe execution flow`

---

## 9. 当前阶段性结论

从后端视角看，本次计划已经把平台推进到“可用于企业级 To B Web 系统业务仿真巡检与测试的最小执行闭环”阶段：

- 有资产优先主链
- 有页面级受控降级
- 有正式执行结果和截图输出
- 有从执行到调度的晋升路径

它还不是最终形态，但已经不再停留在概念设计或半闭环状态。

---

## 10. 后续建议

建议后续工作继续沿以下方向推进：

1. 结合最新的采集同步一致性与资产退役方案，进一步收紧已退役/失配资产的执行与调度边界。
2. 继续补齐更多稳定模块执行能力，减少 runtime 与 compiler 之间的能力缝隙。
3. 在不破坏资产优先原则的前提下，增强 `intent_alias`、route hint 与反馈回写的治理能力。
4. 让上层 CLI、Skills、MCP 与前端统一消费当前已经稳定的结果模型，而不是再定义旁路输出结构。

本次计划的结束标志，不是“已经无后续工作”，而是“后端主链已经具备了继续演进的正确基础”。
