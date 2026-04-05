# 控制台结果接口

**前缀**：`/api/console/results`
**标签**：`console-results`

执行结果的分页查询。

**认证要求**：所有接口需要已登录的控制台用户 Session Cookie。

---

## GET /api/console/results/

查询执行结果列表，支持分页和筛选。

### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| system_id | UUID | 否 | null | 按系统筛选 |
| status | string | 否 | null | 按执行状态筛选 |
| page | int | 否 | `1` | 页码（>= 1） |
| page_size | int | 否 | `20` | 每页条数（1-100） |

### 响应

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| items | list[RunResultItem] | 结果列表 |
| total | int | 总记录数 |
| page | int | 当前页码 |
| page_size | int | 每页条数 |

**RunResultItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 执行记录标识 |
| task_name | string | 任务名称 |
| system_name | string | 系统名称 |
| status | string | 执行状态 |
| duration_ms | int \| null | 执行耗时（毫秒） |
| created_at | datetime | 创建时间 |

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "task_name": "ERP-菜单完整性检查",
      "system_name": "ERP系统",
      "status": "success",
      "duration_ms": 3200,
      "created_at": "2026-04-05T10:00:00Z"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```
