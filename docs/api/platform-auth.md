# 平台令牌（PAT）接口

**前缀**：`/api/v1/platform-auth`
**标签**：`platform-auth`

Personal Access Token 的创建、查询和吊销。PAT 用于 CLI / MCP / Skills 等外部工具与核心 API 交互。

**认证要求**：所有接口需要已登录的控制台用户 Session Cookie。

---

## POST /api/v1/platform-auth/pats

创建新的 PAT。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 令牌名称 |
| expires_in_days | int | 是 | 有效天数（必须是系统配置允许的值） |

### 响应

| 状态码 | 说明 |
|--------|------|
| 201 | 创建成功 |
| 422 | `expires_in_days` 不在允许范围内 |

**响应体**（201）：继承 `PatListItem` 并额外包含 `token` 字段。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 令牌标识 |
| name | string | 令牌名称 |
| token | string | 完整令牌字符串（仅在创建时返回） |
| token_prefix | string | 令牌前缀 |
| allowed_channels | list[string] | 允许的通道 |
| allowed_actions | list[string] \| null | 允许的操作 |
| allowed_system_ids | list[string] \| null | 允许的系统 |
| issued_at | datetime | 签发时间 |
| expires_at | datetime | 过期时间 |
| last_used_at | datetime \| null | 最近使用时间 |
| revoked_at | datetime \| null | 吊销时间 |

> **注意**：`token` 完整值仅在创建响应中返回一次，后续无法再次查看。

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "name": "CLI Token",
  "token": "rlt_live_abc123...",
  "token_prefix": "rlt_live_abc",
  "allowed_channels": ["cli", "mcp"],
  "allowed_actions": null,
  "allowed_system_ids": null,
  "issued_at": "2026-04-05T10:00:00Z",
  "expires_at": "2026-05-05T10:00:00Z",
  "last_used_at": null,
  "revoked_at": null
}
```

---

## GET /api/v1/platform-auth/pats

列出当前用户的所有 PAT。

### 响应

**响应体**：`list[PatListItem]`（不含 `token` 字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 令牌标识 |
| name | string | 令牌名称 |
| token_prefix | string | 令牌前缀 |
| allowed_channels | list[string] | 允许的通道 |
| allowed_actions | list[string] \| null | 允许的操作 |
| allowed_system_ids | list[string] \| null | 允许的系统 |
| issued_at | datetime | 签发时间 |
| expires_at | datetime | 过期时间 |
| last_used_at | datetime \| null | 最近使用时间 |
| revoked_at | datetime \| null | 吊销时间 |

---

## POST /api/v1/platform-auth/pats/{pat_id}:revoke

吊销指定 PAT。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| pat_id | UUID | 令牌标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 204 | 吊销成功（无返回内容） |
| 404 | 令牌不存在 |
