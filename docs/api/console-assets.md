# 控制台资产接口

**前缀**：`/api/console/assets`
**标签**：`console-assets`

资产的浏览与详情查看。

**认证要求**：所有接口需要已登录的控制台用户 Session Cookie。

---

## GET /api/console/assets/

获取所有资产，按系统和页面分组。

### 响应

**响应体**：`list[SystemAssetGroup]`

**SystemAssetGroup**：

| 字段 | 类型 | 说明 |
|------|------|------|
| system_id | UUID | 系统标识 |
| system_name | string | 系统名称 |
| pages | list[PageGroup] | 页面分组列表 |

**PageGroup**：

| 字段 | 类型 | 说明 |
|------|------|------|
| page_name | string | 页面名称 |
| assets | list[AssetItem] | 资产列表 |

**AssetItem**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 资产标识 |
| check_type_label | string | 检查类型标签（中文） |
| version | string | 资产版本 |
| status | string | 资产状态 |

```json
[
  {
    "system_id": "550e8400-e29b-41d4-a716-446655440000",
    "system_name": "ERP系统",
    "pages": [
      {
        "page_name": "首页",
        "assets": [
          {
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "check_type_label": "菜单完整性",
            "version": "v1.2",
            "status": "active"
          }
        ]
      }
    ]
  }
]
```

---

## GET /api/console/assets/{asset_id}

获取资产详情，包含原始采集事实。

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| asset_id | UUID | 资产标识 |

### 响应

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 404 | 资产不存在 |

**响应体**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 资产标识 |
| page_name | string | 页面名称 |
| system_name | string | 系统名称 |
| check_type_label | string | 检查类型标签（中文） |
| version | string | 资产版本 |
| status | string | 资产状态 |
| collected_at | datetime \| null | 采集时间 |
| raw_facts | dict \| null | 原始事实数据（菜单节点、页面元素等） |

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "page_name": "首页",
  "system_name": "ERP系统",
  "check_type_label": "菜单完整性",
  "version": "v1.2",
  "status": "active",
  "collected_at": "2026-04-05T08:30:00Z",
  "raw_facts": {
    "menu_nodes": [
      {"label": "系统管理", "href": "/admin"}
    ]
  }
}
```
