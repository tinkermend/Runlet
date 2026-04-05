# 2026-04-04 precompiled 重试策略 V1 工作总结

## 1. 背景与目标

业务侧反馈历史 Playwright 脚本在以下场景稳定性不足：

- 网络波动
- 页面加载缓慢
- 懒加载导致元素时机不稳定
- 元素短时遮挡

本次工作的目标是：在不改变系统主架构边界的前提下，为 `precompiled` 轨道引入“按失败类型分层重试（最多 3 次）”能力，并补齐可观测审计信息，提升执行稳定性。

## 2. 范围与约束

本次 V1 严格遵循以下范围：

- 仅 `precompiled` 轨道启用重试
- `realtime_probe` 轨道保持单次执行语义，不启用重试
- 不新增数据库迁移
- 重试审计先落在 `queued_jobs.result_payload`

## 3. 方案与实现摘要

### 3.1 Retry Policy 纯函数层

新增文件：

- `backend/src/app/jobs/run_check_retry.py`
- `tests/backend/test_run_check_retry.py`

实现内容：

- `is_retryable_failure`：按失败分类 + 瞬时错误文本兜底判定是否可重试
- `compute_backoff_ms`：指数退避计算
- `build_attempt_entry`：attempt 审计结构构造（JSON 安全）

### 3.2 run_check worker 重试主链路

核心文件：

- `backend/src/app/jobs/run_check_job.py`
- `tests/backend/test_run_check_job.py`

关键改动：

- 在 `run_check` job 层引入 `precompiled` attempt 循环（最多 3 次）
- 可重试失败执行 backoff 后继续；不可重试或上限耗尽则终止
- 对异常路径补齐事务回滚，避免残留运行记录污染
- 对 `ExecutionBlockedError` 保持 `skipped` 语义，且在“先重试后阻断”场景保留 retry metadata

### 3.3 结果审计字段补齐

在 `precompiled` 结果中补齐：

- `attempt_count`
- `retry_exhausted`
- `flaky`
- `retry_policy`
- `attempts`
- `final_failure_category`
- `final_error_message`

并保持 `realtime_probe` 不输出上述重试字段。

### 3.4 回归测试补齐

新增或补强覆盖：

- 首次失败后重试成功
- 不可重试失败仅执行 1 次
- 可重试失败 3 次耗尽
- `realtime_probe` 不重试且不泄露 retry metadata
- 异常型可重试失败耗尽场景 metadata 完整保留
- 先重试后 `ExecutionBlockedError` 场景保持 `skipped` 且 metadata 保留
- `anyio.sleep` 退避序列断言（固定参数后断言 `[1.0, 2.0]`）

## 4. 实施过程中的关键修正

在多轮规格审查与质量审查中，重点修复了以下问题：

- `realtime_probe` payload 被意外注入 retry 字段（已回退）
- 重试异常分支缺少 rollback（已补）
- 重试轨道开关过宽（已收敛为仅 `precompiled`）
- JSON payload 原地修改测试不生效（改为整字典重赋值）
- 异常终止时 retry metadata 丢失（已补）
- `ExecutionBlockedError` 在重试循环中被误吞（已修复）
- “先重试后阻断”场景缺少 metadata（已补）
- `ExecutionBlockedError` 构造参数不匹配（已修复为 `reason=` 关键字）

## 5. 验证结果

最终在 `main` 上完成合并后验证：

- `backend/.venv/bin/pytest tests/backend/test_run_check_retry.py tests/backend/test_run_check_job.py tests/backend/test_runner_service.py -k "failure_category or realtime_probe or run_check" -q`
  - 结果：`35 passed, 30 deselected`
- `backend/.venv/bin/pytest tests/backend -q`
  - 结果：`365 passed`

## 6. 合并与收尾

本次工作已完成本地合并与清理：

- 合并提交：`a0b6e74`（Merge branch `codex/precompiled-retry-policy-v1`）
- 合并后修复提交：`27bd0f1`（修复 `precompiled` 重试路径 `runtime_inputs` 透传与测试桩签名兼容）
- 已删除工作分支与 worktree：`codex/precompiled-retry-policy-v1`

## 7. 当前结论

`precompiled` 轨道已具备 V1 分层重试能力与可审计性，能够显著改善弱网/慢加载场景下的脚本稳定性，同时保持 `realtime_probe` 语义稳定，不破坏现有控制面与执行面边界。
