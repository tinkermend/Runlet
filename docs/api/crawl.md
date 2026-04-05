# 采集触发接口

**前缀**：`/api/v1`
**标签**：`crawl`

触发系统页面采集任务。

---

## POST /api/v1/systems/{system_id}/crawl

触发指定系统的页面采集。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |

### 认证要求

需要 Principal 鉴权。

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| crawl_scope | string | 否 | `"full"` | 采集范围：`full`（全量）/ `incremental`（增量） |
| framework_hint | string | 否 | `"auto"` | 采集框架提示 |
| max_pages | int | 否 | `50` | 最大采集页数（> 0） |

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 采集任务已接受 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |
| job_id | UUID | 异步任务标识 |
| status | string | 固定值 `"accepted"` |
| job_type | string | 固定值 `"crawl"` |
| snapshot_pending | bool | 是否有待处理的快照 |

```json
{
  "system_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_id": "990e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "job_type": "crawl",
  "snapshot_pending": true
}
```
