# Runlet 后端 API 接口文档

> 生成日期：2026-04-05

## 概览

- **基础路径**：所有 API 路由挂载于 `/api/v1`（核心接口）或 `/api/console`（控制台接口）
- **健康检查**：`GET /healthz`
- **总接口数**：31 个
- **认证方式**：
  - 控制台接口：Session Cookie（通过 `/api/console/auth/login` 获取）
  - 核心接口：PAT（Personal Access Token）或 Principal 鉴权

## 接口分组

| 分组 | 前缀 | 说明 | 文档 |
|------|------|------|------|
| 控制台认证 | `/api/console/auth` | 用户登录、登出、身份查询 | [console-auth.md](console-auth.md) |
| 控制台门户 | `/api/console/portal` | 仪表盘、系统管理 | [console-portal.md](console-portal.md) |
| 控制台任务 | `/api/console/tasks` | 任务（page_check）管理 | [console-tasks.md](console-tasks.md) |
| 控制台结果 | `/api/console/results` | 执行结果查询 | [console-results.md](console-results.md) |
| 控制台资产 | `/api/console/assets` | 资产浏览与详情 | [console-assets.md](console-assets.md) |
| 平台令牌 | `/api/v1/platform-auth` | PAT 管理 | [platform-auth.md](platform-auth.md) |
| 认证刷新 | `/api/v1/systems/{system_id}` | 系统认证刷新 | [auth.md](auth.md) |
| 采集触发 | `/api/v1/systems/{system_id}` | 系统采集触发 | [crawl.md](crawl.md) |
| 资产编译 | `/api/v1/snapshots` | 快照资产编译 | [assets.md](assets.md) |
| 发布任务 | `/api/v1/published-jobs` | 已发布任务管理 | [assets.md](assets.md) |
| 检查请求 | `/api/v1/check-requests` | 检查请求提交与查询 | [check-requests.md](check-requests.md) |
| 页面检查 | `/api/v1/page-checks` | 页面检查执行与脚本渲染 | [page-checks.md](page-checks.md) |
| 运行时策略 | `/api/v1/systems/{system_id}` | 认证策略、采集策略管理 | [runtime-policies.md](runtime-policies.md) |

## 通用响应格式

### 成功响应

接口直接返回对应的 Pydantic 模型 JSON。

### 错误响应

所有错误均返回 JSON 格式：

```json
{
  "detail": "错误描述信息",
  "error_type": "BusinessRuleError",
  "request_id": "abc123def456"
}
```

### 常用状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 201 | 资源已创建 |
| 202 | 异步操作已接受 |
| 204 | 操作成功，无返回内容 |
| 401 | 认证失败 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 422 | 业务规则校验失败 / 请求参数无效 |
| 500 | 服务器内部错误 |

## 中间件

- **X-Request-ID**：每个请求自动分配或透传 `X-Request-ID`，响应头中返回
- **请求耗时**：自动记录请求处理时长
