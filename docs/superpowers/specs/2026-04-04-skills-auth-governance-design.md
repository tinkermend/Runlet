# Skills / Web 调用认证与授权治理设计（V1）

**日期：** 2026-04-04  
**作者：** Codex  
**状态：** Draft

---

## 1. 文档定位

本文档定义 Runlet 在以下调用入口上的认证与授权治理方案：

- `web_console -> control_plane -> runner_service`
- `skills -> control_plane -> runner_service`
- `scheduler -> control_plane -> runner_service`

本版目标是先交付可落地、低复杂度的 V1：

1. Web 访问 API 使用会话认证（session/cookie）
2. Skills 调用 API 使用用户临时 token（PAT）
3. 两种凭证在后端统一归一为同一用户主体做授权判定
4. 手动采集触发只允许 Web/CLI，Skills 不允许

---

## 2. 设计目标与非目标

### 2.1 目标

1. 明确区分 Web 会话认证与 Skills token 认证
2. 保持统一授权模型：`principal + channel + action + system`
3. 支持用户在管理平台创建可过期 PAT（如 3 天/7 天）
4. 支持 PAT 吊销、审计、最小权限
5. 不影响现有 `auth_policy/crawl_policy` 调度主链
6. 明确前端 Web 调后端 API 的认证配套改造与配置项

### 2.2 非目标（V1 不做）

1. 不引入 OIDC/SSO
2. 不引入复杂 challenge/二次确认体系
3. 不强制引入 `execution_grant` 双层令牌
4. 不做 `page_check` 级细粒度授权

---

## 3. 方案比较与推荐

### 3.1 方案 A：Web 与 Skills 共用 session

优点：

- 实现最少

缺点：

- AI 侧很难稳定使用浏览器会话
- 会话泄露风险边界不清晰
- 不适合脚本/终端环境注入

### 3.2 方案 B：全面 `execution_grant` 双层令牌

优点：

- 安全边界清晰，防重放强

缺点：

- 第一版复杂度高，交付慢
- 对当前平台演进节奏不友好

### 3.3 方案 C：凭证分离、授权统一（推荐，V1）

做法：

1. Web：`session/cookie`
2. Skills：`PAT(Bearer)`
3. 后端统一判权：`user_id + channel + action + system`

优点：

- 实现复杂度可控
- 满足你当前“用户自己生成临时 token”诉求
- 后续可平滑升级到 `execution_grant`

---

## 4. 核心原则

1. 认证入口分离：Web 与 Skills 不复用同一凭证
2. 授权逻辑统一：所有入口进入同一权限决策层
3. 入口动作白名单：按 `channel-action` 绑定
4. 采集触发边界：手动采集只允许 `web_console/cli`
5. 正式执行边界不变：认证注入仍由服务端统一完成

---

## 5. 通道与动作矩阵（V1）

### 5.1 `skills` 允许动作

1. `create_or_update_published_job`
2. `create_check_request`（仅用于测试任务构建相关检查）

限制：

1. 禁止 `trigger_full_crawl`
2. 禁止 `trigger_incremental_crawl`

### 5.2 `web_console` 允许动作

1. `create_check_request`
2. `create_or_update_published_job`
3. `trigger_full_crawl`
4. `trigger_incremental_crawl`
5. `update_runtime_policy`

### 5.3 `cli` 允许动作

1. `create_or_update_published_job`
2. `trigger_full_crawl`
3. `trigger_incremental_crawl`

### 5.4 `scheduler` 允许动作

1. `trigger_published_job`
2. `trigger_auth_policy`
3. `trigger_crawl_policy`

---

## 6. 关键流程

### 6.1 Web 手动采集触发

1. 用户登录 Web，获得 session
2. Web 调用 `/systems/{id}/crawl`（cookie）
3. 后端解析 session -> user
4. 权限层判定：`channel=web_console + action=trigger_*_crawl + system`
5. 通过则入队；拒绝则返回 403

### 6.2 Skills 自动化任务构建

1. 用户在 Web 创建 PAT（3 天/7 天）
2. PAT 写入用户本地环境变量（例如 `RUNLET_PAT`）
3. Skills 调后端时携带 `Authorization: Bearer <PAT>`
4. 后端解析 PAT -> user
5. 权限层判定：`channel=skills + action + system`
6. 通过则执行任务构建；越权则返回 403

### 6.3 Scheduler 定时触发

1. scheduler 使用内部服务主体身份调用 control plane
2. control plane 按 `channel=scheduler` 与对象归属判权
3. 通过后投递执行；拒绝则写审计并告警

---

## 7. 数据模型（新增/调整）

### 7.1 用户与会话

`users`

- `id`
- `username`
- `password_hash`
- `status`
- `created_at`
- `updated_at`

`user_sessions`

- `id`
- `user_id`
- `session_token_hash`
- `issued_at`
- `expires_at`
- `revoked_at`

### 7.2 PAT（新增）

`user_pats`

- `id`
- `user_id`
- `name`
- `token_prefix`
- `token_hash`
- `allowed_channels`（默认 `skills`）
- `allowed_actions`
- `allowed_system_ids`
- `issued_at`
- `expires_at`
- `last_used_at`
- `revoked_at`

约束：

1. 仅保存 hash，不保存明文 token
2. 明文 token 仅创建时返回一次

### 7.3 授权关系

`user_system_permissions`

- `id`
- `user_id`
- `system_id`
- `role`
- `effect`
- `expires_at`
- `created_at`

### 7.4 调度服务主体

`service_principals`

- `id`
- `code`（如 `scheduler_runtime`）
- `status`
- `allowed_actions`

### 7.5 审计日志

`auth_audit_logs`

- `id`
- `user_id`（可空，服务主体场景）
- `subject_type`（human/service）
- `subject_id`
- `channel`（web_console/skills/cli/scheduler）
- `system_id`
- `action`
- `decision`（allow/deny）
- `reason`
- `request_id`
- `ip`
- `user_agent`
- `created_at`

---

## 8. API 契约（V1）

### 8.1 Web 认证

1. `POST /api/v1/platform-auth/login`
2. `POST /api/v1/platform-auth/logout`
3. `GET /api/v1/platform-auth/me`

### 8.2 PAT 管理

1. `POST /api/v1/platform-auth/pats`（创建，返回一次明文）
2. `GET /api/v1/platform-auth/pats`（仅返回摘要）
3. `POST /api/v1/platform-auth/pats/{pat_id}:revoke`

建议 `expires_in_days` 仅允许：

1. `3`
2. `7`

### 8.3 业务调用约束

1. Web 接口接受 session
2. Skills 接口接受 PAT
3. 同一业务接口可以支持两种认证方式，但必须在服务端标注 `channel`
4. `skills` 调用采集触发接口时必须返回 403

### 8.4 前端配套改造（Web 调后端认证）

1. 前端统一 API client 默认携带 `credentials: "include"`
2. 前端启动时调用 `/api/console/auth/me` 确认登录态，不依赖本地 cookie 字符串判断
3. 前端统一处理 `401`：跳转登录页并清空本地用户态
4. 登录/登出后通过 `/me` 重新拉取用户态，避免前端状态与后端会话漂移
5. 跨域部署时补充 CSRF 防护（双提交 cookie 或等价机制）

---

## 9. 安全要求

1. PAT 最长有效期不超过 7 天（V1）
2. PAT 支持立即吊销
3. PAT 明文只显示一次
4. PAT 日志、报错、审计输出必须脱敏
5. 每次 PAT 使用更新 `last_used_at`
6. 支持按用户查看活跃 PAT 列表

### 9.1 会话与密码配置（`.env`）

后端建议新增：

1. `SESSION_SECRET`：用于会话签名/校验的服务端密钥
2. `SESSION_TTL_HOURS`：Web 会话有效期（默认 8）
3. `PASSWORD_PEPPER`（可选）：密码哈希前附加服务端 pepper

说明：

1. 这里不建议增加“前端 salt”配置
2. 密码哈希应使用算法自带随机 salt（如 argon2/bcrypt）
3. `credential_crypto_secret` 与会话/密码密钥分离管理，不复用

---

## 10. 错误语义

1. `401`：未认证或凭证过期
2. `403`：无系统权限或动作未授权
3. `403`（细分）：入口通道不允许该动作（例如 `skills -> trigger_full_crawl`）
4. `423`：调度触发被策略锁定（如服务主体禁用）

---

## 11. 测试与验收

### 11.1 必测用例

1. Web session 登录成功/失败/过期
2. PAT 创建、过期、吊销、重复使用
3. PAT hash 存储校验（不得落明文）
4. `skills` 触发手动采集稳定返回 403
5. `web/cli` 在有权限时可触发手动采集
6. scheduler 触发不依赖用户会话
7. 审计日志正确区分 `channel` 与 `subject_type`
8. 前端启动态以 `/api/console/auth/me` 为准
9. 前端 API 在会话过期后能统一处理 `401`

### 11.2 验收标准

1. 用户可在 Web 自助创建 3 天/7 天临时 PAT
2. Skills 可通过环境变量 PAT 调用任务构建接口
3. Skills 无法调用手动采集触发
4. Web/CLI 手动采集能力不受影响
5. 全链路具备可追溯审计
6. 前端登录态与后端会话状态一致

---

## 12. 分阶段实施

### Phase 1（本次）

1. 增加 `user_pats` 模型与 PAT 管理 API
2. 业务鉴权增加 `channel-action` 白名单
3. 落地 `skills` 禁止手动采集触发
4. 补齐审计字段与回归测试

### Phase 2

1. 为 scheduler 补充更细粒度委托策略
2. 增加异常访问告警（如 PAT 高频失败）

### Phase 3（可选增强）

1. 引入 `execution_grant` 二次令牌
2. 引入 challenge/审批流
3. 对接 OIDC/SSO

---

## 13. 结论

V1 采用“Web session + Skills PAT + 授权统一判定”的简化方案，能够在不明显增加系统复杂度的前提下，满足你当前的核心诉求：用户可控地发放短期 token 给 AI 对话使用，同时保持平台对系统调用边界、手动采集入口和审计追踪的治理能力。
