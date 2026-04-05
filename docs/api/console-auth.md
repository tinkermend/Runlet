# 控制台认证接口

**前缀**：`/api/console/auth`
**标签**：`console-auth`

控制台用户的会话认证管理，使用 Cookie 机制维持登录态。

---

## POST /api/console/auth/login

控制台用户登录，验证通过后签发 Session Cookie。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 登录成功 |
| 401 | 用户名或密码错误 |
| 403 | 用户已被停用 |

**响应体**（200）：

```json
{
  "ok": true
}
```

**附加行为**：响应通过 `Set-Cookie` 设置 `runlet_session` Cookie（HttpOnly, SameSite=Lax），有效期由 `session_ttl_hours` 配置决定。

---

## POST /api/console/auth/logout

注销当前会话，删除 Cookie。

### 请求体

无

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 注销成功 |

**响应体**：

```json
{
  "ok": true
}
```

**附加行为**：删除 `runlet_session` Cookie。

---

## GET /api/console/auth/me

获取当前登录用户信息。需要已登录的 Session Cookie。

### 请求体

无

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 401 | 未登录或会话已过期 |

**响应体**（200）：

```json
{
  "username": "admin"
}
```

**认证要求**：需要有效的 Session Cookie，未认证返回 401。
