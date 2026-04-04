# 后端 precompiled 轨道分层重试策略设计

**日期：** 2026-04-04  
**作者：** Codex  
**状态：** Draft

---

## 1. 文档定位

本文档定义 Runlet 平台在 `precompiled` 正式执行轨道上的第一阶段稳定性增强方案：

- 引入按失败类型分层的有限重试
- 抵抗网络抖动、页面慢加载等瞬时不稳定
- 不破坏“资产优先、确定性执行、服务端认证注入”的既有架构边界

本文档不涉及 `realtime_probe` 轨道重试、不涉及自由脚本执行、不涉及跨任务重入。

---

## 2. 背景与问题

当前平台已经具备以下稳定性基础：

- `module_plan` 确定性执行主链（`auth.inject_state -> nav.menu_chain -> page.wait_ready -> state.enter -> locator.assert`）
- locator bundle 排序回放与禁用不稳定定位策略（动态 ID、纯 nth-child、hash class）
- 运行 telemetry（主命中、fallback、匹配 rank、上下文/歧义信号）

但业务反馈表明，历史脚本在如下场景仍易出现瞬时失败：

- 网络波动
- 页面加载变慢
- 懒加载导致 ready 时机不稳定
- 页面元素短暂遮挡或时序抖动

当前 `run_check` worker 对 `precompiled` 失败路径是“单次执行后直接失败”，尚无分层重试能力，导致本可恢复的瞬时问题直接暴露为任务失败。

---

## 3. 目标与非目标

### 3.1 目标

1. 在 `precompiled` 轨道引入有限重试能力（最多 3 次）。
2. 仅对“瞬时可恢复”失败重试，避免掩盖确定性资产问题。
3. 让重试过程可审计、可观测、可区分“首跑成功”和“重试后成功（flaky）”。
4. 在不改动核心执行编排边界的前提下，以最小侵入实现落地。

### 3.2 非目标

1. 第一阶段不对 `realtime_probe` 启用重试。
2. 不在 runtime 内做隐式额外动作（例如无限补点、自由 selector 试错）。
3. 不引入跨任务重入队列或复杂分布式重试协调。
4. 不改变资产生命周期阻断语义（retired/missing 仍快速失败或跳过）。

---

## 4. 方案对比

### 4.1 方案 A：仅 precompiled 分层重试（推荐）

- 范围：`precompiled`。
- 策略：按失败类型判定是否可重试，最多 3 次，指数退避 + 抖动。
- 优点：实现成本低、风险可控、可快速验证收益。
- 缺点：`realtime_probe` 的瞬时失败短期内仍无重试保护。

### 4.2 方案 B：precompiled + realtime_probe 同步上

- 范围：两条轨道同时启用。
- 优点：覆盖更完整。
- 缺点：复杂度和排障成本显著提高，且 `realtime_probe` 带反馈回写，早期故障定位更难。

### 4.3 方案 C：统一失败重试 3 次

- 范围：按轨道/类别不区分。
- 优点：实现最快。
- 缺点：会掩盖资产和定位语义问题，不符合平台治理目标。

### 4.4 推荐结论

采用方案 A，先在 `precompiled` 轨道验证一周；若收益明确且未引入明显副作用，再将子集策略推广到 `realtime_probe`。

---

## 5. 架构与边界

### 5.1 变更边界

- 重试逻辑落在 `RunCheckJobHandler`（job 层），不改变 `ModuleExecutor` 执行顺序。
- 每次 attempt 仍调用一次完整 `runner_service.run_page_check(...)`。
- attempt 间由现有 runtime 生命周期隔离，避免复用脏状态。

### 5.2 不变边界

- `control_plane` 仍决定 `execution_track`。
- `runner_service` 仍只消费 `module_plan` 执行。
- `script_renderer` 仍是派生产物，不是正式执行主链。
- 调度主对象仍是 `page_check + asset_version + runtime_policy`。

---

## 6. 执行流程设计

### 6.1 入口判定

在 `RunCheckJobHandler.run()` 中：

1. 若 `execution_track == realtime_probe`：沿用现状（第一阶段不重试）。
2. 若 `execution_track == precompiled`：进入重试循环。

### 6.2 重试循环

1. `attempt=1` 先执行。
2. attempt 失败后执行 `retryable` 判定。
3. 若可重试且未达上限：记录审计，退避等待，进入下一次 attempt。
4. 若不可重试或达上限：立即终止，按现有 FAILED/SKIPPED 语义落库。
5. 任一 attempt 成功：任务最终 `COMPLETED`。

### 6.3 策略参数（第一阶段默认）

- `max_attempts = 3`
- `base_backoff_ms = 1000`
- `jitter_ms = 300`
- 退避序列示例：`1000±jitter`, `2000±jitter`

---

## 7. 可重试判定规则

采用“结构化分类优先、错误文本兜底”的双层判定。

### 7.1 可重试

- `navigation_failed`
- `page_not_ready`
- `runtime_error` 且错误文本命中瞬时模式：
  - `timeout`
  - `net::`
  - `connection reset`
  - `target closed`
  - `temporarily unavailable`

### 7.2 不可重试

- `auth_blocked`
- `assertion_failed`
- `state_not_reached`
- 资产生命周期阻断（retired/missing）
- 定位语义失败（由 `locator.assert` 输出）：
  - `context_mismatch`
  - `ambiguous_match`
  - `locator_all_failed`
  - `element_became_hidden`
- 明显确定性编排错误：
  - `unsupported module`
  - 参数缺失/契约错误

---

## 8. 审计与可观测性

第一阶段不改表结构，重试审计写入 `queued_jobs.result_payload`。

### 8.1 顶层字段

- `attempt_count`
- `retry_exhausted`
- `flaky`（重试后成功）
- `retry_policy`（参数快照）
- `attempts`（attempt 摘要数组）
- `final_failure_category`
- `final_error_message`

### 8.2 attempts[] 字段

- `attempt_no`
- `started_at`
- `finished_at`
- `status`
- `failure_category`
- `retryable`
- `backoff_ms`

### 8.3 产出语义

- 首次成功：`attempt_count=1`, `flaky=false`
- 重试后成功：`attempt_count>1`, `flaky=true`
- 上限耗尽失败：`retry_exhausted=true`

---

## 9. 错误处理

1. `ExecutionBlockedError`：保持现有 `SKIPPED`，不重试。
2. 非 retryable 失败：立即失败，保留首个确定性失败信号。
3. retryable 失败并超上限：失败，并返回最终失败分类与错误信息。
4. 重试期间异常：按当前 attempt 失败处理，不吞异常语义。

---

## 10. 测试与验收

### 10.1 单元/集成测试

新增或扩展 `tests/backend/test_run_check_job.py`：

1. 首次成功：`attempt_count=1`
2. 首次 `page_not_ready`，第二次成功：`flaky=true`
3. 连续 3 次可重试失败：`retry_exhausted=true`
4. `assertion_failed`：不重试
5. `state_not_reached`：不重试
6. `ExecutionBlockedError`：不重试，保持 `SKIPPED`
7. `realtime_probe`：确认不进入重试循环
8. mock `anyio.sleep` 校验退避序列

### 10.2 回归要求

- 现有 runner/crawler/compiler 相关测试不回退
- run_check 新增重试测试全部通过
- result_payload 序列化保持 JSON-safe

### 10.3 线上观察指标（首周）

1. `precompiled` 成功率提升（目标 +5% ~ +10%，按现网基线计算）
2. `flaky` 比例可追踪且不过快增长
3. 非重试类失败占比不被“假成功”掩盖
4. 平均执行时长增幅可控（建议 < 30%）

---

## 11. 实施拆解建议（下一步）

1. 在 `RunCheckJobHandler` 增加 precompiled attempt 循环与退避。
2. 增加 retryable 判定器（结构化分类 + 文本兜底）。
3. 扩展 result_payload 审计字段。
4. 补充 `test_run_check_job.py` 重试回归。
5. 观察一周后决定是否将子集策略推广到 `realtime_probe`。

---

## 12. 结论

第一阶段应以低风险、可审计方式增强 `precompiled` 稳定性，而不是全链路盲目重试。通过“分层重试 + 明确不可重试边界 + 可观测结果语义”，可在保持平台治理原则不变的前提下，实质降低网络波动和慢加载导致的误失败。
