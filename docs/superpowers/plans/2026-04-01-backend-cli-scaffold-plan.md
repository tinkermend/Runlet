# Backend & CLI Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the minimal FastAPI backend, health-check test, and Typer CLI entrypoint so Task 1 passes.

**Architecture:** FastAPI boots through an app factory; routers and settings live in dedicated modules. CLI commands live in a separate package so runtime helpers do not drag in FastAPI.

**Tech Stack:** Python 3.12 (as implied by UV tooling), FastAPI, Typer, uvicorn, pytest, Pydantic BaseSettings.

---

### Task 1: Backend boot test and FastAPI router

**Files:**
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/tests/backend/test_boot.py`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/backend/src/app/api/router.py`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/backend/src/app/config/settings.py`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/backend/src/app/main.py`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/backend/.env.example`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/backend/README.md`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/backend/pyproject.toml`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_app_boots_with_health_router():
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test to confirm the fail (ModuleNotFoundError)**

```
cd worktrees/foundation-step1-2/backend && uv run pytest ../tests/backend/test_boot.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Implement backend skeleton**

Create `app.main.create_app()` that
1. Imports settings from `config.settings`.
2. Instantiates FastAPI and registers routers from `api.router` with the health handler returning `{"status": "ok"}`.
3. Keeps module-level code minimal so the TestClient boots the same app used in production.

`config.settings` should be a `BaseSettings` subclass exposing any env variables (placeholders such as `APP_ENV`, `LOG_LEVEL`). `.env.example` documents them.

`router.py` defines a `/healthz` route returning `{"status": "ok"}`.

`pyproject.toml` lists `[project]` metadata plus dependencies `fastapi`, `uvicorn`, `pydantic`, `pytest`. Include `pytest` under `[project.optional-dependencies]` if desired.

`README.md` explains running `uvicorn app.main:create_app` and the pytest command.

- [ ] **Step 4: Run the same pytest command expecting PASS**

```
cd worktrees/foundation-step1-2/backend && uv run pytest ../tests/backend/test_boot.py -v
```
Expected: PASS with one test run.

- [ ] **Step 5: Verify docs/config files inhabit their paths (manual check)**

Confirm `backend/.env.example` documents `APP_ENV` and `LOG_LEVEL` defaults and that README references them.


### Task 2: CLI scaffold

**Files:**
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/cli/pyproject.toml`
- Create: `/Users/wangpei/src/singe/Runlet/worktrees/foundation-step1-2/cli/src/openweb_cli/main.py`

- [ ] **Step 1: Add Typer CLI skeleton**

`main.py` should:
1. Instantiate `typer.Typer()` as `app`.
2. Define `@app.command("doctor")` that prints `ok`.
3. Guard `if __name__ == "__main__": app()` so it runs via `python -m openweb_cli`.

`pyproject.toml` declares `typer` under dependencies and basic project metadata (name, version, description).

- [ ] **Step 2: Smoke-test the CLI**

```
cd worktrees/foundation-step1-2/cli && uv run python -m openweb_cli doctor
```
Expected: prints `ok`.


### Task 3: Commit the scaffold

**Files:**
- we touched backend/pyproject, README, .env.example, src/app/main.py, src/app/api/router.py, src/app/config/settings.py, cli/pyproject, cli/src/openweb_cli/main.py, tests/backend/test_boot.py, docs/superpowers/specs/..., docs/superpowers/plans/...

- [ ] **Step 1: Stage all new files**

```
git add docs/superpowers/specs/2026-04-01-backend-cli-scaffold-design.md docs/superpowers/plans/2026-04-01-backend-cli-scaffold-plan.md worktrees/foundation-step1-2/backend worktrees/foundation-step1-2/cli worktrees/foundation-step1-2/tests/backend/test_boot.py
```

- [ ] **Step 2: Commit**

```
git commit -m "feat: scaffold ai playwright platform backend and cli"
```

