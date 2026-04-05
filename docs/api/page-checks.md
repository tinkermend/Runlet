# 页面检查接口

**前缀**：`/api/v1`
**标签**：`page-checks`

页面检查的执行、查询与脚本渲染。

---

## POST /api/v1/page-checks/{page_check_id}:run

执行指定页面检查。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| page_check_id | UUID | 页面检查标识 |

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| strictness | string | 否 | `"balanced"` | 严格程度 |
| time_budget_ms | int | 否 | `20000` | 时间预算（毫秒，> 0） |
| triggered_by | string | 否 | `"manual"` | 触发来源 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 202 | 执行请求已接受 |

**响应体**：同 [创建检查请求](check-requests.md#post-apiv1check-requests) 的 `CheckRequestAccepted` 响应。

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

## GET /api/v1/page-assets/{page_asset_id}/checks

查询指定页面资产下的所有检查。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| page_asset_id | UUID | 页面资产标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| page_asset_id | UUID | 页面资产标识 |
| checks | list[PageAssetCheckItem] | 检查列表 |

**PageAssetCheckItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 检查标识 |
| page_asset_id | UUID | 页面资产标识 |
| check_code | string | 检查代码 |
| goal | string | 检查目标 |
| module_plan_id | UUID \| null | 模块计划标识 |
| status | string | 检查状态 |
| drift_status | string | 漂移状态 |
| lifecycle_status | string | 生命周期状态 |

```json
{
  "page_asset_id": "880e8400-e29b-41d4-a716-446655440000",
  "checks": [
    {
      "id": "990e8400-e29b-41d4-a716-446655440000",
      "page_asset_id": "880e8400-e29b-41d4-a716-446655440000",
      "check_code": "menu_completeness",
      "goal": "验证首页菜单完整性",
      "module_plan_id": "aa0e8400-e29b-41d4-a716-446655440000",
      "status": "active",
      "drift_status": "none",
      "lifecycle_status": "published"
    }
  ]
}
```

---

## POST /api/v1/page-checks/{page_check_id}:render-script

渲染页面检查的 Playwright 脚本。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| page_check_id | UUID | 页面检查标识 |

### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| render_mode | string | 否 | `"runtime"` | 渲染模式：`runtime` / `published` |

### 响应

| 状态码 | 说明 |
|--------|------|
| 201 | 渲染成功 |
| 404 | 页面检查不存在或缺少 module_plan |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| page_check_id | UUID | 页面检查标识 |
| script_render_id | UUID | 脚本渲染记录标识 |
| render_mode | string | 渲染模式 |
| script_path | string | 脚本路径（如 `generated/erp_home_menu_completeness_runtime.py`） |
| script_text | string | 完整脚本内容 |

```json
{
  "page_check_id": "660e8400-e29b-41d4-a716-446655440000",
  "script_render_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "render_mode": "runtime",
  "script_path": "generated/erp_home_menu_completeness_runtime.py",
  "script_text": "import re\nfrom playwright.async_api import async_playwright, expect\n..."
}
```
