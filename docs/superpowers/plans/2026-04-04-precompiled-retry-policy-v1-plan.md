# Precompiled Retry Policy V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `precompiled` 轨道落地“按失败类型分层重试（最多 3 次）”，提升弱网和慢加载场景稳定性，并保证重试过程可审计、可观测。

**Architecture:** 保持 `control_plane -> run_check job -> runner_service` 主链不变，把重试控制放在 `run_check` job 层。通过“结构化失败分类优先 + 错误文本兜底”判定是否可重试，使用指数退避与抖动控制重试节奏，并将 attempt 审计写入 `queued_jobs.result_payload`。

**Tech Stack:** FastAPI, SQLModel, AnyIO, Playwright Python (runtime), pytest

---

## 实施约束

- 全流程遵循 `@test-driven-development`：先写失败测试，再最小实现。
- 每个任务结束前执行 `@verification-before-completion` 验证命令。
- 第一阶段仅覆盖 `precompiled`；`realtime_probe` 明确不启用重试。
- 不新增数据库迁移，attempt 审计先落在 `queued_jobs.result_payload`。
- 每个任务独立提交，保持小步可回滚。

---

## File Structure

**Files to Create:**

- `backend/src/app/jobs/run_check_retry.py`
  - 责任：封装 retry policy、retryable 判定、退避时间计算、attempt 审计结构构建。
- `tests/backend/test_run_check_retry.py`
  - 责任：覆盖 retry policy 纯函数行为（失败分类匹配、错误文本匹配、退避策略）。

**Files to Modify:**

- `backend/src/app/jobs/run_check_job.py`
  - 责任：在 `precompiled` 路径引入 attempt 循环；仅 retryable 失败触发重试；将 attempt 审计回写 result payload。
- `tests/backend/test_run_check_job.py`
  - 责任：补充 precompiled 重试主路径回归（重试后成功、上限耗尽、不应重试、realtime_probe 不重试）。
- `CHANGELOG.md`
  - 责任：记录该实施计划文档与后续实现任务入口。

---

### Task 1: 建立 Retry Policy 纯函数层（先测试后实现）

**Files:**
- Create: `tests/backend/test_run_check_retry.py`
- Create: `backend/src/app/jobs/run_check_retry.py`

- [ ] **Step 1: 写失败测试（失败分类判定）**

```python
from app.jobs.run_check_retry import is_retryable_failure


def test_is_retryable_failure_accepts_navigation_and_page_ready():
    assert is_retryable_failure(failure_category="navigation_failed", error_message=None) is True
    assert is_retryable_failure(failure_category="page_not_ready", error_message=None) is True


def test_is_retryable_failure_rejects_assertion_and_auth_blocked():
    assert is_retryable_failure(failure_category="assertion_failed", error_message=None) is False
    assert is_retryable_failure(failure_category="auth_blocked", error_message=None) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_retry.py -v`
Expected: FAIL，提示模块不存在或函数未定义。

- [ ] **Step 3: 最小实现 retry policy 判定函数**

```python
RETRYABLE_FAILURE_CATEGORIES = {"navigation_failed", "page_not_ready"}
NON_RETRYABLE_STEP_FAILURES = {
    "context_mismatch",
    "ambiguous_match",
    "locator_all_failed",
    "element_became_hidden",
    "state_not_reached",
}

TRANSIENT_ERROR_PATTERNS = (
    "timeout",
    "net::",
    "connection reset",
    "target closed",
    "temporarily unavailable",
)
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_retry.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/jobs/run_check_retry.py tests/backend/test_run_check_retry.py
git commit -m "feat: add run-check retry policy utilities"
```

---

### Task 2: 扩展 Policy 细节（错误文本兜底 + 退避计算 + attempt 摘要）

**Files:**
- Modify: `tests/backend/test_run_check_retry.py`
- Modify: `backend/src/app/jobs/run_check_retry.py`

- [ ] **Step 1: 写失败测试（runtime_error 文本兜底 + backoff）**

```python
from app.jobs.run_check_retry import compute_backoff_ms, is_retryable_failure


def test_runtime_error_with_transient_message_is_retryable():
    assert is_retryable_failure(
        failure_category="runtime_error",
        error_message="Timeout 30000ms exceeded",
    ) is True


def test_compute_backoff_ms_doubles_per_attempt():
    assert compute_backoff_ms(attempt_no=1, base_backoff_ms=1000, jitter_ms=0) == 1000
    assert compute_backoff_ms(attempt_no=2, base_backoff_ms=1000, jitter_ms=0) == 2000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_retry.py -v -k "runtime_error or backoff"`
Expected: FAIL，提示函数/分支行为未实现。

- [ ] **Step 3: 最小实现 backoff 与 attempt 审计构造器**

```python
def compute_backoff_ms(*, attempt_no: int, base_backoff_ms: int, jitter_ms: int) -> int:
    base = base_backoff_ms * (2 ** max(attempt_no - 1, 0))
    # first phase deterministic path: jitter=0 in tests, runtime may add bounded random jitter
    return max(0, base + sampled_jitter)
```

```python
def build_attempt_entry(...):
    return {
        "attempt_no": attempt_no,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "failure_category": failure_category,
        "retryable": retryable,
        "backoff_ms": backoff_ms,
    }
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_retry.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/jobs/run_check_retry.py tests/backend/test_run_check_retry.py
git commit -m "feat: add retry backoff and attempt entry builders"
```

---

### Task 3: 在 run_check job 落地 precompiled 重试循环

**Files:**
- Modify: `tests/backend/test_run_check_job.py`
- Modify: `backend/src/app/jobs/run_check_job.py`

- [ ] **Step 1: 写失败测试（precompiled 首次失败后重试成功）**

```python
@pytest.mark.anyio
async def test_run_check_job_retries_precompiled_when_first_attempt_is_retryable_then_succeeds(...):
    await job_runner.run_once()
    refreshed = db_session.get(QueuedJob, queued_job.id)

    assert refreshed.status == "completed"
    assert refreshed.result_payload["status"] == "passed"
    assert refreshed.result_payload["attempt_count"] == 2
    assert refreshed.result_payload["flaky"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_job.py -v -k "retries_precompiled"`
Expected: FAIL，当前实现只有单次执行。

- [ ] **Step 3: 最小实现 precompiled attempt 循环**

```python
if execution_track == "realtime_probe":
    ...  # unchanged
else:
    result, attempt_entries, retry_exhausted = await self._run_precompiled_with_retry(...)
```

```python
for attempt_no in range(1, max_attempts + 1):
    result = await self.runner_service.run_page_check(...)
    if result.status.value == "passed":
        return ...
    retryable = is_retryable_failure(...)
    if not retryable or attempt_no >= max_attempts:
        return ...
    await anyio.sleep(backoff_seconds)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_job.py -v -k "retries_precompiled"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/jobs/run_check_job.py tests/backend/test_run_check_job.py
git commit -m "feat: add precompiled retry loop in run-check worker"
```

---

### Task 4: 补齐边界回归（不应重试与上限耗尽）

**Files:**
- Modify: `tests/backend/test_run_check_job.py`
- Modify: `backend/src/app/jobs/run_check_job.py`

- [ ] **Step 1: 写失败测试（不可重试失败只跑一次）**

```python
@pytest.mark.anyio
async def test_run_check_job_does_not_retry_non_retryable_assertion_failure(...):
    await job_runner.run_once()
    refreshed = db_session.get(QueuedJob, queued_job.id)

    assert refreshed.status == "completed"
    assert refreshed.result_payload["status"] == "failed"
    assert refreshed.result_payload["attempt_count"] == 1
    assert refreshed.result_payload["retry_exhausted"] is False
```

- [ ] **Step 2: 写失败测试（可重试失败连续 3 次后耗尽）**

```python
@pytest.mark.anyio
async def test_run_check_job_marks_retry_exhausted_after_max_attempts(...):
    await job_runner.run_once()
    refreshed = db_session.get(QueuedJob, queued_job.id)

    assert refreshed.status == "completed"
    assert refreshed.result_payload["status"] == "failed"
    assert refreshed.result_payload["attempt_count"] == 3
    assert refreshed.result_payload["retry_exhausted"] is True
```

- [ ] **Step 3: 写失败测试（realtime_probe 不启用重试）**

```python
@pytest.mark.anyio
async def test_run_check_job_keeps_realtime_probe_single_attempt(...):
    await job_runner.run_once()
    refreshed = db_session.get(QueuedJob, queued_realtime_probe_job.id)

    assert refreshed.status == "completed"
    assert refreshed.result_payload["execution_track"] == "realtime_probe"
    assert refreshed.result_payload.get("attempt_count") in {None, 1}
```

- [ ] **Step 4: 最小实现结果 payload 扩展字段**

```python
result_payload.update(
    {
        "attempt_count": attempt_count,
        "retry_exhausted": retry_exhausted,
        "flaky": flaky,
        "retry_policy": retry_policy,
        "attempts": attempts,
        "final_failure_category": final_failure_category,
        "final_error_message": final_error_message,
    }
)
```

- [ ] **Step 5: 跑 task3+task4 相关测试并提交**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_job.py -v -k "retry or realtime_probe"`
Expected: PASS。

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/jobs/run_check_job.py tests/backend/test_run_check_job.py
git commit -m "test: cover retry boundaries for run-check worker"
```

---

### Task 5: 退避调用验证与回归收口

**Files:**
- Modify: `tests/backend/test_run_check_job.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 写失败测试（mock `anyio.sleep` 断言退避序列）**

```python
@pytest.mark.anyio
async def test_run_check_job_uses_exponential_backoff_between_retry_attempts(monkeypatch, ...):
    captured = []

    async def fake_sleep(seconds: float) -> None:
        captured.append(seconds)

    monkeypatch.setattr("app.jobs.run_check_job.anyio.sleep", fake_sleep)
    await job_runner.run_once()

    assert captured == [1.0, 2.0]
```

- [ ] **Step 2: 跑失败测试确认缺口**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_job.py -v -k "exponential_backoff"`
Expected: FAIL。

- [ ] **Step 3: 最小实现并确保 jitter 在测试可控**

```python
# inject jitter provider for deterministic tests
self._jitter_provider = jitter_provider or random.randint
```

- [ ] **Step 4: 执行目标回归集**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_retry.py ../tests/backend/test_run_check_job.py -v`
Expected: PASS。

- [ ] **Step 5: 更新 CHANGELOG 并提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add tests/backend/test_run_check_job.py tests/backend/test_run_check_retry.py backend/src/app/jobs/run_check_job.py backend/src/app/jobs/run_check_retry.py CHANGELOG.md
git commit -m "feat: add precompiled layered retry policy for run-check jobs"
```

---

## 全量验证清单（实施结束前）

- [ ] `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_retry.py ../tests/backend/test_run_check_job.py -v`
- [ ] `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_runner_service.py -v -k "failure_category or realtime_probe"`
- [ ] `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend -v`

---

## 风险与回滚

1. 风险：可重试判定过宽，掩盖确定性失败。
   - 缓解：默认白名单仅 `navigation_failed/page_not_ready/runtime_error(瞬时文本)`。
2. 风险：平均执行时长上升。
   - 缓解：`max_attempts=3`、退避上限、首周观测 `attempt_count` 与耗时。
3. 回滚：仅需回滚 `run_check_retry.py` 与 `run_check_job.py` 重试路径，不影响 schema。

---

## 完成定义（DoD）

1. `precompiled` 轨道支持分层重试，且 `realtime_probe` 轨道语义不变。
2. 重试结果在 `result_payload` 可审计（attempt、flaky、retry_exhausted）。
3. 新增与修改测试通过，且无既有关键回归退化。
4. `CHANGELOG.md` 完整记录该实施变更。
