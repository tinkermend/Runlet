# 资产编译与发布任务接口

**前缀**：`/api/v1`
**标签**：`assets`

资产编译、发布任务的创建与执行管理。

---

## POST /api/v1/snapshots/{snapshot_id}/compile-assets

从快照编译资产。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| snapshot_id | UUID | 快照标识 |

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| compile_scope | string | 否 | `"impacted_pages_only"` | 编译范围 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 编译任务已接受 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| snapshot_id | UUID | 快照标识 |
| job_id | UUID | 异步任务标识 |
| status | string | 固定值 `"accepted"` |
| job_type | string | 固定值 `"asset_compile"` |

```json
{
  "snapshot_id": "aa0e8400-e29b-41d4-a716-446655440000",
  "job_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "job_type": "asset_compile"
}
```

---

## POST /api/v1/published-jobs

创建已发布任务。

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| script_render_id | UUID | 是 | - | 脚本渲染记录标识 |
| page_check_id | UUID | 是 | - | 关联的页面检查标识 |
| schedule_type | string | 否 | `"cron"` | 调度类型 |
| schedule_expr | string | 是 | - | Cron 表达式（标准 5 字段） |
| trigger_source | string | 否 | `"platform"` | 触发来源 |
| enabled | bool | 否 | `true` | 是否启用 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 201 | 创建成功 |
| 422 | 调度表达式无效 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| published_job_id | UUID | 已发布任务标识 |
| page_check_id | UUID | 页面检查标识 |
| script_render_id | UUID | 脚本渲染标识 |
| schedule_expr | string | 调度表达式 |
| state | string | 任务状态 |
| asset_version | string \| null | 资产版本 |

```json
{
  "published_job_id": "cc0e8400-e29b-41d4-a716-446655440000",
  "page_check_id": "dd0e8400-e29b-41d4-a716-446655440000",
  "script_render_id": "ee0e8400-e29b-41d4-a716-446655440000",
  "schedule_expr": "0 */6 * * *",
  "state": "active",
  "asset_version": "v1.2"
}
```

---

## POST /api/v1/published-jobs/{published_job_id}:trigger

手动触发已发布任务执行。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| published_job_id | UUID | 已发布任务标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 触发成功 |
| 404 | 任务不存在 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| published_job_id | UUID | 已发布任务标识 |
| job_run_id | UUID | 执行记录标识 |
| queued_job_id | UUID | 队列任务标识 |
| status | string | 固定值 `"accepted"` |

```json
{
  "published_job_id": "cc0e8400-e29b-41d4-a716-446655440000",
  "job_run_id": "ff0e8400-e29b-41d4-a716-446655440000",
  "queued_job_id": "110e8400-e29b-41d4-a716-446655440000",
  "status": "accepted"
}
```

---

## GET /api/v1/published-jobs/{published_job_id}/runs

查询已发布任务的执行记录。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| published_job_id | UUID | 已发布任务标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 404 | 任务不存在 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| published_job_id | UUID | 已发布任务标识 |
| runs | list[PublishedJobRunItem] | 执行记录列表 |

**PublishedJobRunItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 运行标识 |
| published_job_id | UUID | 已发布任务标识 |
| execution_run_id | UUID \| null | 关联执行运行标识 |
| trigger_source | string | 触发来源：`manual` / `scheduler` |
| run_status | string | 运行状态 |
| scheduled_at | datetime | 调度时间 |
| started_at | datetime \| null | 开始时间 |
| finished_at | datetime \| null | 完成时间 |
| failure_message | string \| null | 失败信息 |

```json
{
  "published_job_id": "cc0e8400-e29b-41d4-a716-446655440000",
  "runs": [
    {
      "id": "220e8400-e29b-41d4-a716-446655440000",
      "published_job_id": "cc0e8400-e29b-41d4-a716-446655440000",
      "execution_run_id": "330e8400-e29b-41d4-a716-446655440000",
      "trigger_source": "scheduler",
      "run_status": "success",
      "scheduled_at": "2026-04-05T06:00:00Z",
      "started_at": "2026-04-05T06:00:01Z",
      "finished_at": "2026-04-05T06:00:05Z",
      "failure_message": null
    }
  ]
}
```
