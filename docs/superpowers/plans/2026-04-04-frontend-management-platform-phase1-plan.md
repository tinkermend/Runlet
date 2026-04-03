# Frontend Management Platform Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first customer-facing web management console in `front/`, including simple web login, task-centric navigation, task creation wizard, system onboarding form, asset browsing, and run result pages backed by frontend-friendly backend APIs.

**Architecture:** Add a new React + Vite SPA under `front/` and keep it as a lightweight task-centric client, not a generic admin template. Extend the FastAPI backend with a minimal console session login and frontend-oriented read/write APIs that continue to route formal execution through existing `control_plane` capabilities; where system onboarding backend support is still missing, align the endpoint shape with the existing onboarding design and execute the corresponding backend plan first or in the same branch.

**Tech Stack:** React, Vite, TypeScript, React Router, TanStack Query, Vitest, Testing Library, FastAPI, Pydantic v2, SQLModel, pytest

---

## File Structure

**Execution Notes:**

- Frontend project root is **`front/`**.
- Before implementing visual pages, execution must use **`ui-ux-pro-max`** to produce key screen designs and interaction guidance.
- Keep customer-facing terminology in the UI; do not expose `storage_state` or raw execution internals in primary flows.

**Files to Create:**

- `front/package.json`
- `front/tsconfig.json`
- `front/vite.config.ts`
- `front/index.html`
- `front/src/main.tsx`
- `front/src/app/router.tsx`
- `front/src/app/app-shell.tsx`
- `front/src/app/providers/query-provider.tsx`
- `front/src/app/providers/auth-provider.tsx`
- `front/src/app/routes/protected-route.tsx`
- `front/src/lib/http/client.ts`
- `front/src/lib/http/types.ts`
- `front/src/features/auth/pages/login-page.tsx`
- `front/src/features/dashboard/pages/dashboard-page.tsx`
- `front/src/features/tasks/pages/task-list-page.tsx`
- `front/src/features/tasks/pages/task-create-page.tsx`
- `front/src/features/tasks/pages/task-detail-page.tsx`
- `front/src/features/assets/pages/asset-browser-page.tsx`
- `front/src/features/assets/pages/asset-detail-page.tsx`
- `front/src/features/systems/pages/system-list-page.tsx`
- `front/src/features/systems/pages/system-onboarding-page.tsx`
- `front/src/features/results/pages/run-results-page.tsx`
- `front/src/test/setup.ts`
- `front/src/features/auth/pages/login-page.test.tsx`
- `front/src/app/router.test.tsx`
- `front/src/features/tasks/pages/task-create-page.test.tsx`
- `front/src/features/assets/pages/asset-browser-page.test.tsx`
- `front/README.md`
- `docs/front/2026-04-04-frontend-platform-ui-foundation.md`
- `docs/front/2026-04-04-frontend-platform-key-screens.md`
- `backend/src/app/api/endpoints/console_auth.py`
- `backend/src/app/api/endpoints/console_portal.py`
- `backend/src/app/api/endpoints/console_tasks.py`
- `backend/src/app/api/endpoints/console_assets.py`
- `backend/src/app/api/endpoints/console_results.py`
- `backend/src/app/infrastructure/security/console_session.py`
- `backend/src/app/domains/control_plane/console_schemas.py`
- `tests/backend/test_console_auth_api.py`
- `tests/backend/test_console_portal_api.py`
- `tests/backend/test_console_tasks_api.py`
- `tests/backend/test_console_assets_api.py`
- `tests/backend/test_console_results_api.py`

**Files to Modify:**

- `backend/src/app/api/router.py` - register console-facing routers
- `backend/src/app/api/deps.py` - add authenticated console-user dependency and shared service wiring
- `backend/src/app/config/settings.py` - add console login/session settings
- `backend/src/app/main.py` - mount cookie middleware or session support if needed
- `backend/src/app/domains/control_plane/service.py` - expose frontend-friendly read/write methods
- `backend/src/app/domains/control_plane/repository.py` - add dashboard, systems, tasks, assets, results query helpers
- `backend/src/app/domains/control_plane/schemas.py` - reuse existing write DTOs where possible
- `CHANGELOG.md`

**Tests to Create or Modify:**

- `tests/backend/test_console_auth_api.py`
- `tests/backend/test_console_portal_api.py`
- `tests/backend/test_console_tasks_api.py`
- `tests/backend/test_console_assets_api.py`
- `tests/backend/test_console_results_api.py`
- `front/src/features/auth/pages/login-page.test.tsx`
- `front/src/app/router.test.tsx`
- `front/src/features/tasks/pages/task-create-page.test.tsx`
- `front/src/features/assets/pages/asset-browser-page.test.tsx`

---

## Task 1: Produce UI Foundation Before Coding

**Files:**

- Create: `docs/front/2026-04-04-frontend-platform-ui-foundation.md`
- Create: `docs/front/2026-04-04-frontend-platform-key-screens.md`
- Modify: `docs/superpowers/specs/2026-04-04-frontend-management-platform-design.md` only if the visual design reveals a scope mismatch

- [ ] **Step 1: Use `ui-ux-pro-max` to define visual foundation**

Deliver:

- dashboard information hierarchy
- task list and task wizard wireframes
- asset browser and raw-fact detail layout
- system onboarding form layout
- run-result detail layout
- design tokens for color, typography, spacing, and status states

- [ ] **Step 2: Save the visual deliverables under `docs/front/`**

Include:

```md
# Frontend Platform UI Foundation

- Primary workflow: create and schedule inspection task
- Visual emphasis: task status, system state, last run result
- Primary CTAs: 新建检查任务 / 立即运行 / 去接入系统
```

- [ ] **Step 3: Manually review against the approved spec**

Checklist:

- task-centric navigation still wins over platform-operator navigation
- raw facts only appear in secondary or detail views
- system onboarding remains a guided form, not a low-level control panel

- [ ] **Step 4: Commit the UI foundation docs**

```bash
git add docs/front/2026-04-04-frontend-platform-ui-foundation.md docs/front/2026-04-04-frontend-platform-key-screens.md
git commit -m "docs: add frontend platform ui foundation"
```

---

## Task 2: Scaffold the React + Vite App in `front/`

**Files:**

- Create: `front/package.json`
- Create: `front/tsconfig.json`
- Create: `front/vite.config.ts`
- Create: `front/index.html`
- Create: `front/src/main.tsx`
- Create: `front/src/app/router.tsx`
- Create: `front/src/app/app-shell.tsx`
- Create: `front/src/app/providers/query-provider.tsx`
- Create: `front/src/app/routes/protected-route.tsx`
- Create: `front/src/test/setup.ts`
- Create: `front/src/app/router.test.tsx`
- Create: `front/README.md`

- [ ] **Step 1: Write the failing router shell test**

```tsx
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

it("redirects anonymous users to /login", async () => {
  render(<RouterProvider router={router} />);
  expect(
    await screen.findByRole("heading", { name: "登录 Runlet 平台" }),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend test to verify it fails**

Run: `cd front && npm test -- --run src/app/router.test.tsx`
Expected: FAIL because the app scaffold and router do not exist

- [ ] **Step 3: Scaffold the app and test tooling**

Include:

- React + Vite + TypeScript
- React Router
- TanStack Query
- Vitest + Testing Library
- Vite dev proxy from `front/` to backend `/api`

- [ ] **Step 4: Add the app shell and protected route**

Create an app shell with left navigation entries:

- `Dashboard`
- `检查任务`
- `采集资产`
- `系统接入`
- `运行结果`

- [ ] **Step 5: Run the router test**

Run: `cd front && npm test -- --run src/app/router.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit the frontend scaffold**

```bash
git add front/package.json front/tsconfig.json front/vite.config.ts front/index.html front/src/main.tsx front/src/app front/src/test/setup.ts front/README.md
git commit -m "feat: scaffold frontend management app"
```

---

## Task 3: Add Simple Console Session Login

**Files:**

- Create: `backend/src/app/infrastructure/security/console_session.py`
- Create: `backend/src/app/api/endpoints/console_auth.py`
- Modify: `backend/src/app/config/settings.py`
- Modify: `backend/src/app/api/deps.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/main.py`
- Create: `tests/backend/test_console_auth_api.py`
- Create: `front/src/app/providers/auth-provider.tsx`
- Create: `front/src/features/auth/pages/login-page.tsx`
- Create: `front/src/features/auth/pages/login-page.test.tsx`

- [ ] **Step 1: Write the failing backend login API test**

```python
def test_console_login_sets_session_cookie(client):
    response = client.post(
        "/api/v1/console-auth/login",
        json={"username": "demo", "password": "secret"},
    )
    assert response.status_code == 200
    assert "console_session=" in response.headers["set-cookie"]
```

- [ ] **Step 2: Write the failing frontend login form test**

```tsx
it("submits username and password then navigates to dashboard", async () => {
  render(<LoginPage />);
  await user.type(screen.getByLabelText("用户名"), "demo");
  await user.type(screen.getByLabelText("密码"), "secret");
  await user.click(screen.getByRole("button", { name: "登录" }));
  expect(loginMutation).toHaveBeenCalled();
});
```

- [ ] **Step 3: Run the backend and frontend auth tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_console_auth_api.py -v`
Expected: FAIL because console auth endpoints do not exist

Run: `cd front && npm test -- --run src/features/auth/pages/login-page.test.tsx`
Expected: FAIL because login page/provider do not exist

- [ ] **Step 4: Implement minimal session-based console auth**

Requirements:

- use env-configured console username/password hash and session secret
- set HTTP-only session cookie
- add `/api/v1/console-auth/login`
- add `/api/v1/console-auth/me`
- add `/api/v1/console-auth/logout`
- keep this auth isolated from target-system `auth_service`

- [ ] **Step 5: Implement frontend auth provider and login page**

Support:

- anonymous redirect to `/login`
- `me` bootstrap on app load
- logout action in the app shell
- error banner on invalid credentials

- [ ] **Step 6: Run auth tests**

Run: `cd backend && uv run pytest ../tests/backend/test_console_auth_api.py -v`
Expected: PASS

Run: `cd front && npm test -- --run src/features/auth/pages/login-page.test.tsx src/app/router.test.tsx`
Expected: PASS

- [ ] **Step 7: Commit console login**

```bash
git add backend/src/app/infrastructure/security/console_session.py backend/src/app/api/endpoints/console_auth.py backend/src/app/config/settings.py backend/src/app/api/deps.py backend/src/app/api/router.py backend/src/app/main.py tests/backend/test_console_auth_api.py front/src/app/providers/auth-provider.tsx front/src/features/auth/pages/login-page.tsx front/src/features/auth/pages/login-page.test.tsx front/src/app/router.tsx front/src/app/app-shell.tsx
git commit -m "feat: add console session login"
```

---

## Task 4: Add Dashboard, Systems, and Results Console APIs

**Files:**

- Create: `backend/src/app/domains/control_plane/console_schemas.py`
- Create: `backend/src/app/api/endpoints/console_portal.py`
- Create: `backend/src/app/api/endpoints/console_results.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/api/router.py`
- Create: `tests/backend/test_console_portal_api.py`
- Create: `tests/backend/test_console_results_api.py`

- [ ] **Step 1: Write the failing dashboard and systems API tests**

```python
def test_console_dashboard_returns_task_and_run_summary(client, seeded_console_state):
    response = client.get("/api/v1/console/dashboard")
    assert response.status_code == 200
    assert response.json()["summary"]["systems_count"] >= 1
```

```python
def test_console_systems_returns_onboarding_states(client, seeded_console_state):
    response = client.get("/api/v1/console/systems")
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] in {"ready", "onboarding", "failed"}
```

- [ ] **Step 2: Write the failing results API test**

```python
def test_console_results_supports_task_and_system_filters(client, seeded_console_state):
    response = client.get("/api/v1/console/results", params={"system_id": seeded_console_state.system_id})
    assert response.status_code == 200
    assert "items" in response.json()
```

- [ ] **Step 3: Run the API tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_console_portal_api.py ../tests/backend/test_console_results_api.py -v`
Expected: FAIL because console read endpoints do not exist

- [ ] **Step 4: Implement frontend-friendly dashboard, systems, and results queries**

Include:

- dashboard summary + recent exceptions
- systems list + onboarding status summary
- result list with task/system/status filters

Schema shape should prefer customer-facing naming such as:

```python
class ConsoleSystemItem(BaseModel):
    id: UUID
    name: str
    status: Literal["ready", "onboarding", "failed"]
    latest_message: str | None = None
```

- [ ] **Step 5: Run the API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_console_portal_api.py ../tests/backend/test_console_results_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit the console portal APIs**

```bash
git add backend/src/app/domains/control_plane/console_schemas.py backend/src/app/api/endpoints/console_portal.py backend/src/app/api/endpoints/console_results.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/service.py backend/src/app/api/router.py tests/backend/test_console_portal_api.py tests/backend/test_console_results_api.py
git commit -m "feat: add dashboard systems and results console apis"
```

---

## Task 5: Add Task Wizard, Task List, and Task Detail APIs

**Files:**

- Create: `backend/src/app/api/endpoints/console_tasks.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/console_schemas.py`
- Modify: `backend/src/app/api/router.py`
- Create: `tests/backend/test_console_tasks_api.py`

- [ ] **Step 1: Write the failing task wizard API tests**

```python
def test_task_wizard_lists_available_pages_and_checks(client, seeded_console_state):
    response = client.get(f"/api/v1/console/systems/{seeded_console_state.system_id}/task-options")
    assert response.status_code == 200
    assert response.json()["pages"][0]["checks"]
```

```python
def test_create_console_task_wraps_page_check_and_schedule(client, seeded_console_state):
    response = client.post(
        "/api/v1/console/tasks",
        json={
            "name": "用户列表巡检",
            "system_id": str(seeded_console_state.system_id),
            "page_check_id": str(seeded_console_state.page_check_id),
            "schedule_preset": "hourly",
        },
    )
    assert response.status_code == 201
```

- [ ] **Step 2: Write the failing task detail API test**

```python
def test_console_task_detail_returns_schedule_runs_and_asset_source(client, seeded_console_state):
    response = client.get(f"/api/v1/console/tasks/{seeded_console_state.published_job_id}")
    assert response.status_code == 200
    assert "asset_source" in response.json()
```

- [ ] **Step 3: Run the task API tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_console_tasks_api.py -v`
Expected: FAIL because console task endpoints do not exist

- [ ] **Step 4: Implement task-facing APIs on top of existing control-plane capabilities**

Support:

- task options by system
- task create endpoint that maps wizard payload to `page_check` + `published_job`
- task list
- task detail with schedule, latest runs, and asset source
- enable/disable and manual trigger actions

Do not expose raw `published_job` jargon in the response schema unless nested in debug/detail fields.

- [ ] **Step 5: Run the task API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_console_tasks_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit task-facing APIs**

```bash
git add backend/src/app/api/endpoints/console_tasks.py backend/src/app/domains/control_plane/service.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/console_schemas.py backend/src/app/api/router.py tests/backend/test_console_tasks_api.py
git commit -m "feat: add console task management apis"
```

---

## Task 6: Add Asset Browser and Raw Fact Detail APIs

**Files:**

- Create: `backend/src/app/api/endpoints/console_assets.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/console_schemas.py`
- Modify: `backend/src/app/api/router.py`
- Create: `tests/backend/test_console_assets_api.py`

- [ ] **Step 1: Write the failing asset browser API tests**

```python
def test_asset_browser_returns_business_friendly_pages_and_checks(client, seeded_console_state):
    response = client.get(f"/api/v1/console/systems/{seeded_console_state.system_id}/assets")
    assert response.status_code == 200
    assert response.json()["pages"][0]["check_items"][0]["label"]
```

```python
def test_asset_detail_includes_raw_fact_sections(client, seeded_console_state):
    response = client.get(f"/api/v1/console/assets/{seeded_console_state.page_asset_id}")
    assert response.status_code == 200
    assert "raw_facts" in response.json()
```

- [ ] **Step 2: Run the asset API tests to verify they fail**

Run: `cd backend && uv run pytest ../tests/backend/test_console_assets_api.py -v`
Expected: FAIL because console asset endpoints do not exist

- [ ] **Step 3: Implement customer-facing asset browse and detail APIs**

Requirements:

- default response lists pages and check items in business-friendly labels
- detail view includes raw menu/page/element facts only in nested detail fields
- surface asset version and drift/lifecycle summary when available

- [ ] **Step 4: Run the asset API tests**

Run: `cd backend && uv run pytest ../tests/backend/test_console_assets_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit asset APIs**

```bash
git add backend/src/app/api/endpoints/console_assets.py backend/src/app/domains/control_plane/service.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/console_schemas.py backend/src/app/api/router.py tests/backend/test_console_assets_api.py
git commit -m "feat: add console asset browser apis"
```

---

## Task 7: Implement Dashboard, Systems, and Results Pages in `front/`

**Files:**

- Create: `front/src/lib/http/client.ts`
- Create: `front/src/lib/http/types.ts`
- Create: `front/src/features/dashboard/pages/dashboard-page.tsx`
- Create: `front/src/features/systems/pages/system-list-page.tsx`
- Create: `front/src/features/systems/pages/system-onboarding-page.tsx`
- Create: `front/src/features/results/pages/run-results-page.tsx`
- Modify: `front/src/app/router.tsx`
- Modify: `front/src/app/app-shell.tsx`

- [ ] **Step 1: Write the failing page smoke tests**

```tsx
it("shows dashboard summary cards", async () => {
  renderWithRouter("/dashboard");
  expect(await screen.findByText("今日运行次数")).toBeInTheDocument();
});
```

```tsx
it("shows system onboarding form fields", async () => {
  renderWithRouter("/systems/new");
  expect(screen.getByLabelText("系统名称")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend page tests to verify they fail**

Run: `cd front && npm test -- --run src/app/router.test.tsx`
Expected: FAIL because the pages and routes do not exist

- [ ] **Step 3: Implement pages using the UI foundation docs**

Requirements:

- dashboard cards + recent exception list
- systems list with onboarding statuses
- onboarding form with customer-safe labels
- results page with filters and table/list view

- [ ] **Step 4: Wire API calls through a shared HTTP client**

Use relative `/api/v1` requests so Vite proxy can handle local development.

- [ ] **Step 5: Run the frontend tests**

Run: `cd front && npm test -- --run src/app/router.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit dashboard/systems/results pages**

```bash
git add front/src/lib/http front/src/features/dashboard/pages/dashboard-page.tsx front/src/features/systems/pages/system-list-page.tsx front/src/features/systems/pages/system-onboarding-page.tsx front/src/features/results/pages/run-results-page.tsx front/src/app/router.tsx front/src/app/app-shell.tsx
git commit -m "feat: add dashboard systems and results pages"
```

---

## Task 8: Implement Task Wizard, Task List, Task Detail, and Asset Browser Pages

**Files:**

- Create: `front/src/features/tasks/pages/task-list-page.tsx`
- Create: `front/src/features/tasks/pages/task-create-page.tsx`
- Create: `front/src/features/tasks/pages/task-detail-page.tsx`
- Create: `front/src/features/assets/pages/asset-browser-page.tsx`
- Create: `front/src/features/assets/pages/asset-detail-page.tsx`
- Create: `front/src/features/tasks/pages/task-create-page.test.tsx`
- Create: `front/src/features/assets/pages/asset-browser-page.test.tsx`
- Modify: `front/src/app/router.tsx`

- [ ] **Step 1: Write the failing task wizard and asset browser tests**

```tsx
it("lets the user select system page check and schedule preset", async () => {
  renderWithRouter("/tasks/new");
  expect(await screen.findByText("选择检查目标")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建任务" })).toBeDisabled();
});
```

```tsx
it("keeps raw facts behind the asset detail page", async () => {
  renderWithRouter("/assets");
  expect(await screen.findByText("页面")).toBeInTheDocument();
  expect(screen.queryByText("原始菜单事实")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the feature tests to verify they fail**

Run: `cd front && npm test -- --run src/features/tasks/pages/task-create-page.test.tsx src/features/assets/pages/asset-browser-page.test.tsx`
Expected: FAIL because task and asset pages do not exist

- [ ] **Step 3: Implement the task list and task wizard**

Support:

- system selection
- page/check selection
- strictness and time budget
- schedule preset selection
- confirmation step

- [ ] **Step 4: Implement task detail and asset browser/detail pages**

Support:

- task tabs: 概览 / 调度 / 运行记录 / 资产来源
- asset list with system/page/check grouping
- raw facts visible only in detail page expansion

- [ ] **Step 5: Run the feature tests**

Run: `cd front && npm test -- --run src/features/tasks/pages/task-create-page.test.tsx src/features/assets/pages/asset-browser-page.test.tsx`
Expected: PASS

- [ ] **Step 6: Run a production build**

Run: `cd front && npm run build`
Expected: PASS and emit a `dist/` build with no TypeScript errors

- [ ] **Step 7: Commit task and asset pages**

```bash
git add front/src/features/tasks/pages/task-list-page.tsx front/src/features/tasks/pages/task-create-page.tsx front/src/features/tasks/pages/task-detail-page.tsx front/src/features/assets/pages/asset-browser-page.tsx front/src/features/assets/pages/asset-detail-page.tsx front/src/features/tasks/pages/task-create-page.test.tsx front/src/features/assets/pages/asset-browser-page.test.tsx front/src/app/router.tsx
git commit -m "feat: add task wizard and asset browser pages"
```

---

## Task 9: Verify End-to-End Flow, Update Docs, and Close the Slice

**Files:**

- Modify: `front/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Verify backend console endpoints**

Run: `cd backend && uv run pytest ../tests/backend/test_console_auth_api.py ../tests/backend/test_console_portal_api.py ../tests/backend/test_console_tasks_api.py ../tests/backend/test_console_assets_api.py ../tests/backend/test_console_results_api.py -v`
Expected: PASS

- [ ] **Step 2: Verify frontend tests and build**

Run: `cd front && npm test -- --run`
Expected: PASS

Run: `cd front && npm run build`
Expected: PASS

- [ ] **Step 3: Run a manual smoke check with local servers**

Run backend:

```bash
cd backend && uv run uvicorn app.main:create_app --factory --reload
```

Run frontend:

```bash
cd front && npm run dev
```

Manual checklist:

- login works
- dashboard loads
- system onboarding form submits
- task wizard creates a task
- manual trigger and run history view load
- asset detail reveals raw facts only on detail view

- [ ] **Step 4: Update docs and changelog**

Document:

- frontend local setup
- required console auth env vars
- Vite proxy behavior
- known dependency on backend onboarding support

- [ ] **Step 5: Commit verification and docs**

```bash
git add front/README.md CHANGELOG.md
git commit -m "docs: document frontend management platform setup"
```

---

## Dependencies and Order Notes

- If the backend work from `docs/superpowers/plans/2026-04-03-web-system-onboarding-teardown-plan.md` is not yet implemented, either:
  - complete its minimal onboarding add-path before Task 7, or
  - implement only the frontend-safe onboarding subset required by `系统接入` and leave delete/edit lifecycle work for the dedicated onboarding slice.
- Keep frontend copy customer-facing. Any raw `page_check`, `published_job`, `script_render`, or locator details belong in detail/debug views only.
- Do not let frontend code bypass backend orchestration for `auth refresh`, `crawl`, or `compile assets`.
