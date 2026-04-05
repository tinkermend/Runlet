# 认证刷新接口

**前缀**：`/api/v1`
**标签**：`auth`

触发系统认证状态刷新。

---

## POST /api/v1/systems/{system_id}/auth:refresh

刷新指定系统的认证状态。由服务端统一注入，不依赖本地浏览器登录态。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |

### 认证要求

需要 Principal 鉴权，且需 `refresh_auth` 操作权限。

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 刷新任务已接受 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |
| job_id | UUID | 异步任务标识 |
| status | string | 固定值 `"accepted"` |
| job_type | string | 固定值 `"auth_refresh"` |

```json
{
  "system_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_id": "880e8400-e29b-41d4-a716-446655440000",
  "status": "accepted",
  "job_type": "auth_refresh"
}
```
