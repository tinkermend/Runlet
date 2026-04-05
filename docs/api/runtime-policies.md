# 运行时策略接口

**前缀**：`/api/v1`
**标签**：`runtime-policies`

系统级认证策略和采集策略的管理。

---

## 认证策略（auth-policy）

### GET /api/v1/systems/{system_id}/auth-policy

获取指定系统的认证策略。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |

#### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 策略标识 |
| system_id | UUID | 系统标识 |
| enabled | bool | 是否启用 |
| state | string | 策略状态 |
| schedule_expr | string | 调度表达式 |
| auth_mode | string | 认证模式 |
| captcha_provider | string | 验证码提供商 |

**auth_mode 可选值**：

| 值 | 说明 |
|----|------|
| `none` | 无认证 |
| `image_captcha` | 图片验证码 |
| `slider_captcha` | 滑块验证码 |
| `sms_captcha` | 短信验证码 |

```json
{
  "id": "cc0e8400-e29b-41d4-a716-446655440000",
  "system_id": "550e8400-e29b-41d4-a716-446655440000",
  "enabled": true,
  "state": "active",
  "schedule_expr": "0 */6 * * *",
  "auth_mode": "image_captcha",
  "captcha_provider": "ddddocr"
}
```

---

### PUT /api/v1/systems/{system_id}/auth-policy

创建或更新指定系统的认证策略（Upsert）。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| enabled | bool | 否 | `true` | 是否启用 |
| schedule_expr | string | 是 | - | 调度表达式 |
| auth_mode | string | 是 | - | 认证模式：`none` / `image_captcha` / `slider_captcha` / `sms_captcha` |
| captcha_provider | string | 否 | `"ddddocr"` | 验证码提供商 |

#### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 更新成功 |

**响应体**：同 GET 响应。

---

## 采集策略（crawl-policy）

### GET /api/v1/systems/{system_id}/crawl-policy

获取指定系统的采集策略。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |

#### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 策略标识 |
| system_id | UUID | 系统标识 |
| enabled | bool | 是否启用 |
| state | string | 策略状态 |
| schedule_expr | string | 调度表达式 |
| crawl_scope | string | 采集范围 |

**crawl_scope 可选值**：由 `CrawlScope` 枚举定义。

```json
{
  "id": "dd0e8400-e29b-41d4-a716-446655440000",
  "system_id": "550e8400-e29b-41d4-a716-446655440000",
  "enabled": true,
  "state": "active",
  "schedule_expr": "0 2 * * *",
  "crawl_scope": "full"
}
```

---

### PUT /api/v1/systems/{system_id}/crawl-policy

创建或更新指定系统的采集策略（Upsert）。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| enabled | bool | 否 | `true` | 是否启用 |
| schedule_expr | string | 是 | - | 调度表达式 |
| crawl_scope | string | 否 | `"full"` | 采集范围 |

#### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 更新成功 |

**响应体**：同 GET 响应。
