# Crawler Stale Auth Refresh Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `crawler_service` 增加通用的失效认证态判定、一次性认证刷新和单次重试能力，解决“库里有 `auth_state`，但真实采集回退登录页”的问题。

**Architecture:** 保持 `run_crawl()` 作为唯一采集入口，在首次 crawl 后对聚合事实做通用失效态判定。命中后调用可选注入的 `auth_service` 做一次 `refresh_auth_state`，刷新成功后重跑一次 crawl，失败则返回首次结果并附加诊断 warning。

**Tech Stack:** FastAPI, Pydantic v2, SQLModel, Playwright Python, pytest

---

## 文件结构

### 重点修改文件

- `backend/src/app/domains/crawler_service/service.py`
  增加失效态判定、单次认证刷新和一次性重试编排。
- `tests/backend/test_crawler_service.py`
  增加自动刷新成功/失败回归测试，并覆盖正常路径不触发刷新。
- `CHANGELOG.md`
  记录本轮通用失效态自动刷新重试增强。

### 可复用依赖

- `backend/src/app/domains/auth_service/service.py`
  复用现有 `refresh_auth_state()` 能力，不改其登录主逻辑。
- `backend/src/app/domains/crawler_service/schemas.py`
  复用现有 `message / warning_messages` 字段承载诊断信息，若实现需要，再做最小扩展。

---

### Task 1: 用失败测试锁定自动刷新成功路径

**Files:**
- Modify: `tests/backend/test_crawler_service.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 写失败测试，描述首次 crawl 命中失效态后会自动刷新并重试成功**

```python
@pytest.mark.anyio
async def test_run_crawl_refreshes_stale_auth_state_once_and_retries_successfully(...):
    auth_service = FakeAuthService(success=True)
    crawler_service = CrawlerService(..., auth_service=auth_service)

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert auth_service.calls == [seeded_auth_state.system_id]
    assert result.status == "success"
    assert "auth_state_auto_refreshed" in result.warning_messages
```

- [ ] **Step 2: 运行单测，确认当前实现不会自动刷新**

Run: `uv run --project backend pytest tests/backend/test_crawler_service.py -k "refreshes_stale_auth_state_once" -q`  
Expected: FAIL，表现为 `auth_service.calls == []` 或构造器不接受 `auth_service`。

- [ ] **Step 3: 实现最小 fake 夹具，避免测试依赖真实 Playwright 登录**

```python
class FakeAuthService:
    def __init__(self, *, result):
        self.result = result
        self.calls = []

    async def refresh_auth_state(self, *, system_id):
        self.calls.append(system_id)
        return self.result
```

- [ ] **Step 4: 再次运行单测，确保失败原因已聚焦到生产代码缺失**

Run: `uv run --project backend pytest tests/backend/test_crawler_service.py -k "refreshes_stale_auth_state_once" -q`  
Expected: FAIL，且失败点落在 `CrawlerService` 未触发 refresh/retry。

### Task 2: 用失败测试锁定刷新失败和不重复重试路径

**Files:**
- Modify: `tests/backend/test_crawler_service.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 写失败测试，描述 refresh 失败时返回首次结果且不无限重试**

```python
@pytest.mark.anyio
async def test_run_crawl_returns_initial_result_when_auth_refresh_fails(...):
    auth_service = FakeAuthService(success=False)
    crawler_service = CrawlerService(..., auth_service=auth_service)

    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert auth_service.calls == [seeded_auth_state.system_id]
    assert result.pages_saved == 1
    assert "auth_state_refresh_failed" in result.warning_messages
```

- [ ] **Step 2: 运行这两个新增测试，确认当前仓库仍为红灯**

Run: `uv run --project backend pytest tests/backend/test_crawler_service.py -k "stale_auth_state or auth_refresh_fails" -q`  
Expected: FAIL。

### Task 3: 在 `CrawlerService` 中实现失效态判定与单次自动刷新重试

**Files:**
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 为 `CrawlerService` 增加可选 `auth_service` 依赖**

```python
def __init__(..., auth_service=None, ...):
    self.auth_service = auth_service
```

- [ ] **Step 2: 提取单次 crawl 执行 helper，避免 `run_crawl()` 递归复制逻辑**

```python
async def _execute_crawl_once(...):
    ...
    return result, combined
```

- [ ] **Step 3: 实现通用失效态判定 helper**

```python
def _looks_like_stale_auth_result(self, *, combined):
    page_routes = {page.route_path for page in combined.pages}
    has_login_route = any("login" in route for route in page_routes if route)
    return (
        len(page_routes) <= 2
        and len(combined.menus) == 0
        and len(combined.elements) <= 2
        and ("state_probe_baseline_degraded" in combined.warning_messages)
        and has_login_route
    )
```

- [ ] **Step 4: 在 `run_crawl()` 中接入一次性 refresh + retry**

```python
initial_result = await self._execute_crawl_once(...)
if self._should_refresh_stale_auth(...):
    refresh_result = await self.auth_service.refresh_auth_state(system_id=system_id)
    if refresh_result.status == "success":
        retry_result = await self._execute_crawl_once(...)
        retry_result.warning_messages = [*retry_result.warning_messages, "auth_state_auto_refreshed"]
        return retry_result
```

- [ ] **Step 5: 运行新增测试，确认转绿**

Run: `uv run --project backend pytest tests/backend/test_crawler_service.py -k "stale_auth_state or auth_refresh_fails" -q`  
Expected: PASS。

### Task 4: 回归验证并更新变更记录

**Files:**
- Modify: `CHANGELOG.md`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 更新 `CHANGELOG.md`**

```markdown
- 新增采集失效认证态自动恢复：`crawler_service` 现可对“已注入旧 auth_state 但真实回退登录页”的结果做通用判定，触发一次 `auth refresh` 并仅重试一次 crawl。
```

- [ ] **Step 2: 运行 crawler 全量回归**

Run: `uv run --project backend pytest tests/backend/test_crawler_service.py -q`  
Expected: PASS。

- [ ] **Step 3: 如有必要，补跑 auth 相关回归**

Run: `uv run --project backend pytest tests/backend/test_auth_service.py -q`  
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/src/app/domains/crawler_service/service.py \
  tests/backend/test_crawler_service.py \
  CHANGELOG.md \
  docs/superpowers/specs/2026-04-06-crawler-stale-auth-refresh-retry-design.md \
  docs/superpowers/plans/2026-04-06-crawler-stale-auth-refresh-retry-plan.md
git commit -m "feat: auto refresh stale crawl auth state once"
```
