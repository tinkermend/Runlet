# AI Playwright 执行平台接口契约样例

**日期：** 2026-04-01  
**作者：** Codex  
**状态：** Draft

---

## 1. 设计原则

接口设计遵循：

1. 对外统一走控制面 API
2. 结构化请求优先，不直接传自由自然语言给执行层
3. 返回值必须带上资产、版本、认证和执行轨道信息
4. 脚本发布与调度接口必须绑定资产版本

API 路径示例统一使用 `/api/v1/...`。

---

## 2. 创建检查请求

### `POST /api/v1/check-requests`

用途：

- 提交一次正式检查请求
- 由控制面自动命中系统、页面、检查项
- 自动决定走预编译轨还是实时轨

请求示例：

```json
{
  "system_hint": "ERP",
  "page_hint": "用户管理",
  "check_goal": "table_render",
  "strictness": "balanced",
  "time_budget_ms": 20000,
  "request_source": "skill"
}
```

响应示例：

```json
{
  "request_id": "req_01",
  "plan_id": "plan_01",
  "resolved": {
    "system_id": "sys_erp",
    "page_asset_id": "asset_users",
    "page_check_id": "check_users_table_render"
  },
  "execution_track": "precompiled",
  "auth_policy": "server_injected",
  "status": "accepted"
}
```

---

## 3. 查询检查请求状态

### `GET /api/v1/check-requests/{request_id}`

响应示例：

```json
{
  "request_id": "req_01",
  "status": "completed",
  "execution_track": "precompiled",
  "auth_status": "reused",
  "result": {
    "passed": true,
    "failure_category": null,
    "duration_ms": 4821
  },
  "resolved": {
    "system_code": "erp",
    "page_asset_key": "users.list",
    "check_code": "table_render",
    "asset_version": "v12"
  },
  "artifacts": [
    {
      "type": "screenshot",
      "path": "artifacts/run_01/final.png"
    }
  ]
}
```

---

## 4. 直接运行某个页面检查

### `POST /api/v1/page-checks/{page_check_id}:run`

请求示例：

```json
{
  "strictness": "strict",
  "time_budget_ms": 15000,
  "triggered_by": "manual"
}
```

响应示例：

```json
{
  "request_id": "req_02",
  "plan_id": "plan_02",
  "page_check_id": "check_users_table_render",
  "execution_track": "precompiled",
  "status": "accepted"
}
```

---

## 5. 列出页面可用检查

### `GET /api/v1/page-assets/{page_asset_id}/checks`

响应示例：

```json
{
  "page_asset_id": "asset_users",
  "asset_key": "users.list",
  "asset_version": "v12",
  "checks": [
    {
      "page_check_id": "check_users_page_open",
      "check_code": "page_open",
      "status": "ready"
    },
    {
      "page_check_id": "check_users_table_render",
      "check_code": "table_render",
      "status": "ready"
    }
  ]
}
```

---

## 6. 触发认证刷新

### `POST /api/v1/systems/{system_id}/auth:refresh`

响应示例：

```json
{
  "system_id": "sys_erp",
  "status": "accepted",
  "job_type": "auth_refresh"
}
```

---

## 7. 触发采集

### `POST /api/v1/systems/{system_id}/crawl`

请求示例：

```json
{
  "crawl_scope": "full",
  "framework_hint": "auto",
  "max_pages": 50
}
```

响应示例：

```json
{
  "system_id": "sys_erp",
  "status": "accepted",
  "job_type": "crawl",
  "snapshot_pending": true
}
```

---

## 8. 触发资产编译

### `POST /api/v1/snapshots/{snapshot_id}/compile-assets`

请求示例：

```json
{
  "compile_scope": "impacted_pages_only"
}
```

响应示例：

```json
{
  "snapshot_id": "snap_01",
  "status": "accepted",
  "job_type": "asset_compile"
}
```

---

## 9. 渲染 Playwright 脚本

### `POST /api/v1/page-checks/{page_check_id}:render-script`

请求示例：

```json
{
  "render_mode": "published",
  "target_runtime": "playwright-python",
  "include_comments": true
}
```

响应示例：

```json
{
  "script_render_id": "render_01",
  "page_check_id": "check_users_table_render",
  "asset_version": "v12",
  "render_version": "r3",
  "render_mode": "published",
  "status": "completed",
  "script_path": "renders/check_users_table_render_v12_r3.py"
}
```

---

## 10. 发布调度任务

### `POST /api/v1/published-jobs`

请求示例：

```json
{
  "script_render_id": "render_01",
  "page_check_id": "check_users_table_render",
  "schedule_type": "cron",
  "schedule_expr": "0 */2 * * *",
  "trigger_source": "platform",
  "enabled": true
}
```

响应示例：

```json
{
  "published_job_id": "job_01",
  "status": "created",
  "bound_asset_version": "v12",
  "auth_policy": "platform-runner-only"
}
```

---

## 11. 手动触发调度任务

### `POST /api/v1/published-jobs/{published_job_id}:trigger`

请求示例：

```json
{
  "triggered_by": "manual"
}
```

响应示例：

```json
{
  "published_job_id": "job_01",
  "job_run_id": "job_run_01",
  "status": "accepted"
}
```

---

## 12. 查询调度任务执行历史

### `GET /api/v1/published-jobs/{published_job_id}/runs`

响应示例：

```json
{
  "published_job_id": "job_01",
  "runs": [
    {
      "job_run_id": "job_run_01",
      "execution_run_id": "run_01",
      "status": "passed",
      "triggered_by": "cron",
      "started_at": "2026-04-01T10:00:00Z",
      "finished_at": "2026-04-01T10:00:06Z"
    }
  ]
}
```

---

## 13. 统一状态语义建议

### 13.1 资产状态

- `draft`
- `ready`
- `suspect`
- `stale`
- `disabled`

### 13.2 执行轨道

- `precompiled`
- `realtime`

### 13.3 认证状态

- `reused`
- `refreshed`
- `blocked`

### 13.4 执行结果

- `accepted`
- `running`
- `passed`
- `failed`
- `blocked`

### 13.5 失败分类

- `auth_invalid`
- `navigation_failed`
- `locator_drift`
- `route_mismatch`
- `assertion_failed`
- `asset_stale_blocked`
- `runtime_generation_failed`

---

## 14. MCP / CLI 对应关系建议

### MCP 适合暴露

- 查询系统
- 查询页面资产
- 查询检查项
- 查询执行结果
- 受控转调 `POST /api/v1/check-requests`

### CLI 适合封装

- `auth refresh`
- `crawl run`
- `asset compile`
- `page-check run`
- `script render`
- `job trigger`

CLI 和 MCP 都应调用正式 API，而不是复制核心领域逻辑。
