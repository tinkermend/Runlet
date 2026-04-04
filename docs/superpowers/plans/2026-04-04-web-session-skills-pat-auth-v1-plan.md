# Web Session + Skills PAT Auth V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入过度复杂机制的前提下，落地“Web 用 session、Skills 用 PAT、后端统一按 channel-action-system 判权”的 V1 认证体系，并补齐前端会话联动改造。

**Architecture:** 认证入口分离：`/api/console/*` 走会话 cookie，`/api/v1` 中 skills 相关调用走 PAT。授权统一收敛到后端判权层（principal + channel + action + system），对 `skills -> 手动采集触发` 做硬性拒绝。前端保留 cookie 模式，增加 `/api/console/auth/me` 启动态校验与统一 401 处理，避免仅靠本地 cookie 字符串判断。

**Tech Stack:** FastAPI, Pydantic v2, SQLModel, Alembic, pytest, React + Vite + Vitest

---

## File Structure

**Files to Create:**

- `backend/src/app/infrastructure/db/models/identity.py`  
  Responsibility: 定义 `users / user_sessions / user_pats / auth_audit_logs` 表模型与枚举字段。
- `backend/src/app/infrastructure/security/password_hash.py`  
  Responsibility: 密码哈希与校验（argon2/bcrypt 封装，支持可选 pepper）。
- `backend/src/app/infrastructure/security/session_auth.py`  
  Responsibility: 生成/校验 Web session token，持久化 `user_sessions`，处理 TTL 与吊销。
- `backend/src/app/infrastructure/security/pat_auth.py`  
  Responsibility: 生成/哈希/校验 PAT，解析 `Bearer` 凭证并映射到用户主体。
- `backend/src/app/api/deps_auth.py`  
  Responsibility: 统一 principal 解析依赖（console session / skills PAT / scheduler principal）和 channel 注入。
- `backend/src/app/api/endpoints/platform_auth.py`  
  Responsibility: PAT 管理接口（创建、列表、吊销）。
- `backend/src/app/domains/control_plane/authorization.py`  
  Responsibility: `channel-action-system` 判权与 `skills` 手动采集触发阻断。
- `backend/alembic/versions/0012_identity_and_pat_auth.py`  
  Responsibility: 新增身份认证相关表与索引。
- `tests/backend/test_platform_auth_api.py`  
  Responsibility: PAT 管理 API 覆盖（3/7 天 TTL、仅一次返回明文、吊销后失效）。
- `tests/backend/test_authz_channel_policy.py`  
  Responsibility: channel-action 权限矩阵回归，重点覆盖 `skills -> trigger_*_crawl = 403`。
- `front/src/features/auth/pages/pat-management-page.tsx`  
  Responsibility: Web 控制台 PAT 管理页（创建、复制提示、列表、吊销）。
- `front/src/features/auth/pages/pat-management-page.test.tsx`  
  Responsibility: PAT 管理页交互测试。

**Files to Modify:**

- `backend/src/app/config/settings.py`  
  Add: `session_secret`, `session_ttl_hours`, `password_pepper`(optional), `pat_max_ttl_days`, `pat_allowed_ttl_days`.
- `backend/src/app/main.py`  
  Register 新增 `platform_auth` 路由。
- `backend/src/app/api/router.py`  
  Include `platform_auth` router 到 `/api/v1`。
- `backend/src/app/api/endpoints/console_auth.py`  
  改为 DB + hash + session 表驱动，不再依赖单一 `console_username/password` 直接比对。
- `backend/src/app/api/endpoints/console_portal.py`  
- `backend/src/app/api/endpoints/console_tasks.py`  
- `backend/src/app/api/endpoints/console_assets.py`  
- `backend/src/app/api/endpoints/console_results.py`  
  Add: `require_console_user` 依赖，未登录统一 401。
- `backend/src/app/api/endpoints/check_requests.py`  
  Add: skills PAT principal 解析与 channel/action 判权。
- `backend/src/app/api/endpoints/crawl.py`  
  Add: channel/action 判权，阻断 `skills` 手动采集触发。
- `tests/backend/test_initial_schema.py`  
  扩展新表断言与 metadata 对齐断言。
- `tests/backend/test_console_auth_api.py`  
  更新为 DB 会话语义并验证 `/me` 与过期/无效 session。
- `tests/backend/test_console_tasks_api.py`  
- `tests/backend/test_console_portal_api.py`  
- `tests/backend/test_console_assets_api.py`  
- `tests/backend/test_console_results_api.py`  
  增加“未登录 401”覆盖。
- `tests/backend/test_check_requests_api.py`  
- `tests/backend/test_job_submission_api.py`  
  增加 skills PAT 成功路径与无凭证拒绝路径。
- `front/src/app/providers/auth-provider.tsx`  
  启动时改为调用 `/api/console/auth/me` 同步登录态，引入 `isLoadingAuth`。
- `front/src/app/routes/protected-route.tsx`  
  处理 auth bootstrap loading，避免闪跳。
- `front/src/lib/http/client.ts`  
  统一封装 API 错误类型（含 status），提供 401 统一处理点。
- `front/src/features/auth/pages/login-page.tsx`  
  登录成功后触发 `/me` 重拉，保持前后端状态一致。
- `front/src/app/router.tsx`  
  增加 PAT 管理页路由。
- `front/src/app/app-shell.tsx`  
  增加 PAT 管理入口导航。
- `front/src/app/router.test.tsx`  
- `front/src/features/auth/pages/login-page.test.tsx`  
  更新为 `/me` 驱动的登录态逻辑。
- `backend/.env.example`  
  增加 session/PAT 相关变量说明。
- `backend/README.md`  
  补充 Web 会话与 PAT 配置说明。
- `CHANGELOG.md`  
  记录本次实现计划和落地结果。

**Reference Skills:**

- `@superpowers/test-driven-development`
- `@superpowers/verification-before-completion`

---

### Task 1: 建立身份模型与配置基线（Schema + Settings）

**Files:**

- Create: `backend/src/app/infrastructure/db/models/identity.py`
- Create: `backend/alembic/versions/0012_identity_and_pat_auth.py`
- Modify: `backend/src/app/config/settings.py`
- Modify: `tests/backend/test_initial_schema.py`
- Test: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: 先写失败测试（表与配置项）**

```python
def test_initial_schema_exposes_identity_tables(db_engine):
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())
    assert {"users", "user_sessions", "user_pats", "auth_audit_logs"} <= table_names
```

```python
def test_settings_expose_session_and_pat_controls():
    assert hasattr(settings, "session_secret")
    assert hasattr(settings, "session_ttl_hours")
    assert hasattr(settings, "pat_max_ttl_days")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k "identity or session or pat"`  
Expected: FAIL（新表/新配置尚不存在）

- [ ] **Step 3: 实现最小模型与配置**

```python
class User(BaseModel, table=True):
    __tablename__ = "users"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=128)
    password_hash: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
```

```python
class Settings(BaseSettings):
    session_secret: str = Field(default="runlet-dev-session-secret")
    session_ttl_hours: int = Field(default=8, ge=1)
    pat_max_ttl_days: int = Field(default=7, ge=1)
```

- [ ] **Step 4: 编写 Alembic 迁移并更新 metadata 导入**

```python
def upgrade() -> None:
    op.create_table("users", ...)
    op.create_table("user_sessions", ...)
    op.create_table("user_pats", ...)
    op.create_table("auth_audit_logs", ...)
```

- [ ] **Step 5: 回归测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k "identity or session or pat"`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/infrastructure/db/models/identity.py backend/alembic/versions/0012_identity_and_pat_auth.py backend/src/app/config/settings.py tests/backend/test_initial_schema.py
git commit -m "feat: add identity schema and auth settings baseline"
```

---

### Task 2: 重构 Console 会话认证并保护 `/api/console/*`

**Files:**

- Create: `backend/src/app/infrastructure/security/password_hash.py`
- Create: `backend/src/app/infrastructure/security/session_auth.py`
- Create: `backend/src/app/api/deps_auth.py`
- Modify: `backend/src/app/api/endpoints/console_auth.py`
- Modify: `backend/src/app/api/endpoints/console_portal.py`
- Modify: `backend/src/app/api/endpoints/console_tasks.py`
- Modify: `backend/src/app/api/endpoints/console_assets.py`
- Modify: `backend/src/app/api/endpoints/console_results.py`
- Test: `tests/backend/test_console_auth_api.py`
- Test: `tests/backend/test_console_portal_api.py`
- Test: `tests/backend/test_console_tasks_api.py`
- Test: `tests/backend/test_console_assets_api.py`
- Test: `tests/backend/test_console_results_api.py`

- [ ] **Step 1: 先补失败测试（未登录 401）**

```python
def test_console_dashboard_requires_auth(client):
    resp = client.get("/api/console/portal/dashboard")
    assert resp.status_code == 401
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_console_*_api.py -v`  
Expected: FAIL（当前 console 业务接口尚未受保护）

- [ ] **Step 3: 实现会话依赖与用户解析**

```python
def require_console_user(
    console_session: str | None = Cookie(default=None),
    session: ConsoleDep = Depends(get_console_db),
) -> User:
    # token -> user_session -> user
    ...
```

- [ ] **Step 4: 为 console 业务接口统一挂载依赖**

```python
@router.get("/dashboard", response_model=DashboardSummary)
def get_dashboard(
    _: User = Depends(require_console_user),
    session: ConsoleDep = Depends(get_console_db),
) -> DashboardSummary:
    ...
```

- [ ] **Step 5: 更新 `console_auth` 为 DB 会话模式**

```python
@router.post("/login")
async def login(...):
    user = repo.get_user_by_username(body.username)
    verify_password(...)
    session_token = issue_session(...)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_console_*_api.py -v`  
Expected: PASS

- [ ] **Step 7: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/infrastructure/security/password_hash.py backend/src/app/infrastructure/security/session_auth.py backend/src/app/api/deps_auth.py backend/src/app/api/endpoints/console_auth.py backend/src/app/api/endpoints/console_portal.py backend/src/app/api/endpoints/console_tasks.py backend/src/app/api/endpoints/console_assets.py backend/src/app/api/endpoints/console_results.py tests/backend/test_console_auth_api.py tests/backend/test_console_portal_api.py tests/backend/test_console_tasks_api.py tests/backend/test_console_assets_api.py tests/backend/test_console_results_api.py
git commit -m "feat: enforce db-backed console session auth"
```

---

### Task 3: 落地 PAT 管理 API（创建/列表/吊销）

**Files:**

- Create: `backend/src/app/infrastructure/security/pat_auth.py`
- Create: `backend/src/app/api/endpoints/platform_auth.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/main.py`
- Test: `tests/backend/test_platform_auth_api.py`

- [ ] **Step 1: 先写失败测试（3/7 天、一次性明文、吊销）**

```python
def test_create_pat_returns_plaintext_once(client, auth_cookie):
    resp = client.post("/api/v1/platform-auth/pats", json={"name": "my-skill", "expires_in_days": 3}, cookies=auth_cookie)
    assert resp.status_code == 201
    assert "token" in resp.json()
```

```python
def test_revoke_pat_blocks_future_use(client, auth_cookie):
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_platform_auth_api.py -v`  
Expected: FAIL（接口尚不存在）

- [ ] **Step 3: 实现 PAT 生成/哈希/校验**

```python
def issue_pat(*, user_id: UUID, ttl_days: int) -> tuple[str, UserPat]:
    plaintext = "rpat_" + secrets.token_urlsafe(32)
    token_hash = hash_pat(plaintext)
    ...
```

- [ ] **Step 4: 挂载 PAT 管理路由**

```python
api_router.include_router(platform_auth_router, prefix="/platform-auth")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_platform_auth_api.py -v`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/infrastructure/security/pat_auth.py backend/src/app/api/endpoints/platform_auth.py backend/src/app/api/router.py backend/src/app/main.py tests/backend/test_platform_auth_api.py
git commit -m "feat: add platform PAT management APIs"
```

---

### Task 4: 接入统一授权层与 channel-action 阻断

**Files:**

- Create: `backend/src/app/domains/control_plane/authorization.py`
- Modify: `backend/src/app/api/deps_auth.py`
- Modify: `backend/src/app/api/endpoints/check_requests.py`
- Modify: `backend/src/app/api/endpoints/crawl.py`
- Modify: `backend/src/app/api/endpoints/auth.py`
- Create: `tests/backend/test_authz_channel_policy.py`
- Modify: `tests/backend/test_check_requests_api.py`
- Modify: `tests/backend/test_job_submission_api.py`

- [ ] **Step 1: 先写失败测试（skills 不能手动采集）**

```python
def test_skills_pat_cannot_trigger_crawl(client, skills_pat):
    resp = client.post(f"/api/v1/systems/{system_id}/crawl", json={"crawl_scope": "full"}, headers={"Authorization": f"Bearer {skills_pat}"})
    assert resp.status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_authz_channel_policy.py ../tests/backend/test_check_requests_api.py -v`  
Expected: FAIL（授权阻断尚未生效）

- [ ] **Step 3: 实现统一授权判定器**

```python
def authorize(*, principal: Principal, channel: str, action: str, system_id: UUID | None) -> None:
    if channel == "skills" and action in {"trigger_full_crawl", "trigger_incremental_crawl"}:
        raise HTTPException(status_code=403, detail="channel action not allowed")
```

- [ ] **Step 4: 在关键 API 注入授权**

```python
principal = resolve_principal(...)
authorize(principal=principal, channel=principal.channel, action="create_check_request", system_id=resolved_system_id)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_authz_channel_policy.py ../tests/backend/test_check_requests_api.py ../tests/backend/test_job_submission_api.py -v`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/authorization.py backend/src/app/api/deps_auth.py backend/src/app/api/endpoints/check_requests.py backend/src/app/api/endpoints/crawl.py backend/src/app/api/endpoints/auth.py tests/backend/test_authz_channel_policy.py tests/backend/test_check_requests_api.py tests/backend/test_job_submission_api.py
git commit -m "feat: enforce channel-action authorization policy"
```

---

### Task 5: 前端会话认证配套改造（`/me` 启动态 + 统一 401）

**Files:**

- Modify: `front/src/lib/http/client.ts`
- Modify: `front/src/app/providers/auth-provider.tsx`
- Modify: `front/src/app/routes/protected-route.tsx`
- Modify: `front/src/features/auth/pages/login-page.tsx`
- Modify: `front/src/app/router.test.tsx`
- Modify: `front/src/features/auth/pages/login-page.test.tsx`
- Create: `front/src/app/providers/auth-provider.test.tsx`

- [ ] **Step 1: 先写失败测试（启动时走 `/me`）**

```tsx
it("boots auth state from /api/console/auth/me", async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ username: "admin" }) });
  ...
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/front && npm run test -- auth-provider router login-page`  
Expected: FAIL（当前 provider 仍依赖 cookie 字符串）

- [ ] **Step 3: 改造 `auth-provider` 与保护路由**

```tsx
const [state, setState] = useState({ isAuthenticated: false, isLoadingAuth: true, username: null });
useEffect(() => { void bootstrapFromMe(); }, []);
```

```tsx
if (isLoadingAuth) return null;
if (!isAuthenticated) return <Navigate to="/login" replace />;
```

- [ ] **Step 4: 统一 API 错误状态（支持 401）**

```ts
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/front && npm run test -- auth-provider router login-page`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add front/src/lib/http/client.ts front/src/app/providers/auth-provider.tsx front/src/app/routes/protected-route.tsx front/src/features/auth/pages/login-page.tsx front/src/app/providers/auth-provider.test.tsx front/src/app/router.test.tsx front/src/features/auth/pages/login-page.test.tsx
git commit -m "feat: bootstrap web auth state from /me and handle 401"
```

---

### Task 6: 前端 PAT 管理页与文档收口

**Files:**

- Create: `front/src/features/auth/pages/pat-management-page.tsx`
- Create: `front/src/features/auth/pages/pat-management-page.test.tsx`
- Modify: `front/src/app/router.tsx`
- Modify: `front/src/app/app-shell.tsx`
- Modify: `backend/.env.example`
- Modify: `backend/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 先写失败测试（PAT 页面创建与吊销）**

```tsx
it("creates PAT with 3-day ttl and shows token once", async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ token: "rpat_xxx" }) });
  ...
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/front && npm run test -- pat-management-page`  
Expected: FAIL（页面与路由尚不存在）

- [ ] **Step 3: 实现 PAT 管理页面并接线路由导航**

```tsx
{ path: "/auth/pats", element: <PatManagementPage /> }
```

- [ ] **Step 4: 更新后端配置文档与变更日志**

```dotenv
SESSION_SECRET=change-me
SESSION_TTL_HOURS=8
PASSWORD_PEPPER=
PAT_MAX_TTL_DAYS=7
PAT_ALLOWED_TTL_DAYS=3,7
```

- [ ] **Step 5: 运行前后端关键回归**

Run: `cd /Users/wangpei/src/singe/Runlet/front && npm run test -- pat-management-page router`  
Expected: PASS

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_platform_auth_api.py ../tests/backend/test_console_auth_api.py ../tests/backend/test_authz_channel_policy.py -v`  
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add front/src/features/auth/pages/pat-management-page.tsx front/src/features/auth/pages/pat-management-page.test.tsx front/src/app/router.tsx front/src/app/app-shell.tsx backend/.env.example backend/README.md CHANGELOG.md
git commit -m "feat: add PAT management UI and auth config docs"
```

---

### Task 7: 全量验证与收尾

**Files:**

- Verify only (no required code files)

- [ ] **Step 1: 运行后端认证相关全量回归**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_console_*_api.py ../tests/backend/test_platform_auth_api.py ../tests/backend/test_authz_channel_policy.py ../tests/backend/test_check_requests_api.py -v`  
Expected: PASS

- [ ] **Step 2: 运行前端测试**

Run: `cd /Users/wangpei/src/singe/Runlet/front && npm run test`  
Expected: PASS

- [ ] **Step 3: 手工烟雾验证**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet
# 1) Web 登录 -> /api/console/auth/me 正常
# 2) Web 手动触发 crawl 正常
# 3) skills PAT 调 check-request 正常
# 4) skills PAT 调 crawl 返回 403
```

Expected: 行为与 V1 设计一致

- [ ] **Step 4: 最终提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add -A
git commit -m "feat: deliver web-session and skills-pat auth v1"
```
