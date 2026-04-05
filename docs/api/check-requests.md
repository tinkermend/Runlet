# 检查请求接口

**前缀**：`/api/v1/check-requests`
**标签**：`check-requests`

检查请求的提交、状态查询与发布。

---

## POST /api/v1/check-requests

提交新的检查请求。

### 认证要求

需要 Principal 鉴权，且需 `create_check_request` 操作权限。

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| system_hint | string | 是 | - | 系统提示（系统名称或标识） |
| page_hint | string | 否 | null | 页面提示（页面名称或路径） |
| check_goal | string | 是 | - | 检查目标描述 |
| strictness | string | 否 | `"balanced"` | 严格程度 |
| time_budget_ms | int | 否 | `20000` | 时间预算（毫秒，> 0） |
| request_source | string | 否 | `"api"` | 请求来源 |
| template_code | string | 否 | null | 模板代码 |
| template_version | string | 否 | null | 模板版本 |
| carrier_hint | string | 否 | null | 载体类型：`table` / `list` |
| template_params | dict | 否 | null | 模板参数 |

> **注意**：当提供 `template_code`、`template_version`、`carrier_hint` 或 `template_params` 中任意一个时，`template_code`、`template_version` 和 `carrier_hint` 必须同时提供。

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 检查请求已接受 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 请求标识 |
| plan_id | UUID | 执行计划标识 |
| page_check_id | UUID \| null | 匹配的页面检查标识（预编译路径时有值） |
| execution_track | string | 执行轨道：`precompiled`（预编译） / `realtime_probe`（实时探测） |
| auth_policy | string | 认证策略 |
| job_id | UUID | 异步任务标识 |
| status | string | 固定值 `"accepted"` |

```json
{
  "request_id": "440e8400-e29b-41d4-a716-446655440000",
  "plan_id": "550e8400-e29b-41d4-a716-446655440000",
  "page_check_id": "660e8400-e29b-41d4-a716-446655440000",
  "execution_track": "precompiled",
  "auth_policy": "server_injected",
  "job_id": "770e8400-e29b-41d4-a716-446655440000",
  "status": "accepted"
}
```

---

## POST /api/v1/check-requests:candidates

查询匹配的检查候选列表。

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| system_hint | string | 是 | - | 系统提示 |
| page_hint | string | 否 | null | 页面提示 |
| intent | string | 是 | - | 检查意图 |
| slot_hints | dict | 否 | null | 槽位提示 |

### 响应

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| candidates | list[CheckCandidateItem] | 候选列表 |

**CheckCandidateItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| page_asset_id | UUID | 页面资产标识 |
| page_check_id | UUID | 页面检查标识 |
| asset_key | string | 资产键 |
| check_code | string | 检查代码 |
| goal | string | 检查目标 |
| alias_confidence | float | 别名置信度 |
| success_rate | float | 历史成功率 |
| sample_count | int | 采样次数 |
| recency_score | float | 新鲜度评分 |
| rank_score | float | 综合排名评分 |

```json
{
  "candidates": [
    {
      "page_asset_id": "880e8400-e29b-41d4-a716-446655440000",
      "page_check_id": "990e8400-e29b-41d4-a716-446655440000",
      "asset_key": "erp_home",
      "check_code": "menu_completeness",
      "goal": "验证首页菜单完整性",
      "alias_confidence": 0.95,
      "success_rate": 0.98,
      "sample_count": 120,
      "recency_score": 0.9,
      "rank_score": 0.94
    }
  ]
}
```

---

## GET /api/v1/check-requests/{request_id}

查询检查请求的状态。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 请求标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 请求标识 |
| plan_id | UUID \| null | 执行计划标识 |
| page_check_id | UUID \| null | 页面检查标识 |
| execution_track | string \| null | 执行轨道 |
| auth_policy | string \| null | 认证策略 |
| status | string | 请求状态 |

```json
{
  "request_id": "440e8400-e29b-41d4-a716-446655440000",
  "plan_id": "550e8400-e29b-41d4-a716-446655440000",
  "page_check_id": "660e8400-e29b-41d4-a716-446655440000",
  "execution_track": "precompiled",
  "auth_policy": "server_injected",
  "status": "running"
}
```

---

## GET /api/v1/check-requests/{request_id}/result

查询检查请求的执行结果。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 请求标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 请求标识 |
| plan_id | UUID \| null | 执行计划标识 |
| page_check_id | UUID \| null | 页面检查标识 |
| execution_track | string \| null | 执行轨道：`precompiled` / `realtime_probe` |
| execution_summary | ExecutionSummary \| null | 执行摘要 |
| artifacts | list[ArtifactItem] | 产物列表 |
| needs_recrawl | bool | 是否需要重新采集 |
| needs_recompile | bool | 是否需要重新编译 |

**ExecutionSummary**：

| 字段 | 类型 | 说明 |
|------|------|------|
| execution_run_id | UUID | 执行运行标识 |
| status | string | 执行状态 |
| auth_status | string \| null | 认证状态 |
| duration_ms | int \| null | 执行耗时（毫秒） |
| failure_category | string \| null | 失败分类 |
| asset_version | string \| null | 资产版本 |
| snapshot_version | string \| null | 快照版本 |
| final_url | string \| null | 最终页面 URL |
| page_title | string \| null | 页面标题 |

**ArtifactItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 产物标识 |
| artifact_kind | string | 产物类型 |
| result_status | string | 结果状态 |
| artifact_uri | string \| null | 产物 URI |
| payload | dict \| null | 产物数据 |
| created_at | datetime | 创建时间 |

---

## POST /api/v1/check-requests/{request_id}:publish

将检查请求发布为定时任务。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 请求标识 |

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| schedule_expr | string | 是 | - | Cron 表达式（标准 5 字段） |
| trigger_source | string | 否 | `"platform"` | 触发来源 |
| enabled | bool | 否 | `true` | 是否启用 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 201 | 发布成功 |

**响应体**：同 [创建已发布任务](assets.md#post-apiv1published-jobs) 的 `PublishedJobCreated` 响应。
