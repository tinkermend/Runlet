# 控制台门户接口

**前缀**：`/api/console/portal`
**标签**：`console-portal`

控制台门户页面数据接口，提供仪表盘概览和系统管理功能。

**认证要求**：所有接口需要已登录的控制台用户 Session Cookie。

---

## GET /api/console/portal/dashboard

获取仪表盘概览数据。

### 响应

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| today_runs | int | 今日执行次数 |
| active_tasks | int | 活跃任务数 |
| systems_count | int | 系统总数 |
| recent_failures_24h | int | 最近 24 小时失败数 |
| recent_exceptions | list[dict] | 最近异常列表 |

```json
{
  "today_runs": 42,
  "active_tasks": 10,
  "systems_count": 3,
  "recent_failures_24h": 2,
  "recent_exceptions": [
    {"message": "...", "timestamp": "2026-04-05T10:00:00Z"}
  ]
}
```

---

## GET /api/console/portal/systems

获取所有系统列表。

### 响应

**响应体**：`list[SystemItem]`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 系统标识 |
| name | string | 系统名称 |
| base_url | string | 系统基础 URL |
| status | string | 系统状态：`ready` / `onboarding` / `failed` |
| task_count | int | 关联任务数量 |

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "ERP系统",
    "base_url": "https://erp.example.com",
    "status": "ready",
    "task_count": 5
  }
]
```

---

## POST /api/console/portal/systems

接入新系统。

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| name | string | 是 | - | 系统名称 |
| base_url | string | 是 | - | 系统基础 URL |
| auth_type | string | 否 | `"none"` | 认证类型：`none` / `username_password` / `cookie` |
| username | string | 否 | null | 用户名（auth_type 非 none 时使用） |
| password | string | 否 | null | 密码（auth_type 非 none 时使用） |

### 响应

| 状态码 | 说明 |
|--------|------|
| 201 | 系统创建成功 |

**响应体**（201）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 新系统标识 |
| name | string | 系统名称 |
| base_url | string | 系统基础 URL |
| status | string | 系统初始状态 |

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "ERP系统",
  "base_url": "https://erp.example.com",
  "status": "onboarding"
}
```
