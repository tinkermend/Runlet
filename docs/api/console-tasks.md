# 控制台任务接口

**前缀**：`/api/console/tasks`
**标签**：`console-tasks`

任务（即 page_check）的增删查改与手动触发。

**认证要求**：所有接口需要已登录的控制台用户 Session Cookie。

---

## GET /api/console/tasks/wizard-options

获取任务创建向导所需选项（可用系统列表和检查类型）。

### 响应

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| systems | list[SystemItem] | 可用系统列表（同门户系统列表） |
| check_types | list[string] | 可用检查类型列表 |

**check_types 可选值**：

| 值 | 说明 |
|----|------|
| `menu_completeness` | 菜单完整性 |
| `element_existence` | 页面元素存在性 |
| `login_flow` | 登录流程 |
| `table_render` | 表格渲染 |
| `form_submit` | 表单提交 |
| `page_load` | 页面加载 |

```json
{
  "systems": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "ERP系统",
      "base_url": "https://erp.example.com",
      "status": "ready",
      "task_count": 5
    }
  ],
  "check_types": ["menu_completeness", "element_existence", "login_flow", "table_render", "form_submit", "page_load"]
}
```

---

## GET /api/console/tasks/

获取任务列表。

### 响应

**响应体**：`list[TaskItem]`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 任务标识 |
| name | string | 任务名称 |
| system_name | string | 所属系统名称 |
| status | string | 任务状态：`active` / `disabled` |
| last_run_at | datetime \| null | 最近执行时间 |
| last_run_status | string \| null | 最近执行状态 |
| schedule_preset | string | 调度预设：`hourly` / `daily` / `manual` |

```json
[
  {
    "id": "abc123",
    "name": "ERP-菜单完整性检查",
    "system_name": "ERP系统",
    "status": "active",
    "last_run_at": "2026-04-05T10:00:00Z",
    "last_run_status": "success",
    "schedule_preset": "daily"
  }
]
```

---

## POST /api/console/tasks/

创建新任务。

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | 任务名称 |
| system_id | UUID | 是 | - | 所属系统 |
| check_types | list[string] | 是 | - | 检查类型列表 |
| schedule_preset | string | 否 | `"manual"` | 调度预设：`hourly` / `daily` / `manual` |
| timeout_seconds | int | 否 | `30` | 超时时间（秒） |

### 响应

| 状态码 | 说明 |
|--------|------|
| 201 | 任务创建成功 |
| 404 | 指定系统不存在 |

**响应体**（201）：

```json
{
  "id": "abc123",
  "name": "ERP-菜单完整性检查"
}
```

---

## GET /api/console/tasks/{task_id}

获取任务详情，含最近 10 次执行记录。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 404 | 任务不存在 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 任务标识 |
| name | string | 任务名称 |
| system_name | string | 所属系统名称 |
| status | string | 任务状态 |
| schedule_preset | string | 调度预设 |
| check_types | list[string] | 检查类型 |
| recent_runs | list[RunResultItem] | 最近执行记录（最多 10 条） |

**RunResultItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 执行记录标识 |
| task_name | string | 任务名称 |
| system_name | string | 系统名称 |
| status | string | 执行状态 |
| duration_ms | int \| null | 执行耗时（毫秒） |
| created_at | datetime | 创建时间 |

---

## POST /api/console/tasks/{task_id}/trigger

手动触发任务执行。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 任务标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 触发成功 |
| 404 | 任务不存在 |

**响应体**（202）：

```json
{
  "ok": true,
  "run_id": "def456"
}
```
