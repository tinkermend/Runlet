# Backend SQLModel 对齐修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第一阶段 backend 在真实异步数据库路径上的 `sqlmodel`/`sqlalchemy` 会话错配问题，并恢复 Alembic 迁移可用性。

**Architecture:** 保持现有 control-plane、模型和 Alembic 结构不变，只修正异步 session 工厂返回类型、迁移配置和缺失运行时依赖。业务查询继续统一走 `sqlmodel` 风格接口，避免在仓储层混用不同 session 能力。

**Tech Stack:** FastAPI、SQLModel、Alembic、pytest、PostgreSQL、Redis

---

### Task 1: 锁定异步 session 回归

**Files:**
- Create: `tests/backend/test_db_session.py`
- Modify: `backend/src/app/infrastructure/db/session.py`

- [ ] **Step 1: 写失败测试**

```python
def test_create_session_factory_returns_sqlmodel_async_session():
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && ./.venv/bin/pytest ../tests/backend/test_db_session.py -v`
Expected: FAIL，返回的 session 不是 `sqlmodel.ext.asyncio.session.AsyncSession`

- [ ] **Step 3: 最小修复 session 工厂**

```python
return async_sessionmaker(
    create_db_engine(database_url),
    class_=AsyncSession,
    expire_on_commit=False,
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && ./.venv/bin/pytest ../tests/backend/test_db_session.py -v`
Expected: PASS

### Task 2: 恢复 Alembic 基线迁移

**Files:**
- Modify: `backend/alembic.ini`
- Test: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: 使用现有失败测试作为回归保护**

Run: `cd backend && ./.venv/bin/pytest ../tests/backend/test_initial_schema.py -v`
Expected: FAIL，`KeyError: logger_gi`

- [ ] **Step 2: 最小修复 logger 配置**

```ini
[loggers]
keys = root,sqlalchemy,alembic
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd backend && ./.venv/bin/pytest ../tests/backend/test_initial_schema.py -v`
Expected: PASS

### Task 3: 补齐真实异步运行依赖并做端到端验证

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 补齐运行时依赖**

```toml
"greenlet>=3.0",
```

- [ ] **Step 2: 同步虚拟环境**

Run: `cd backend && uv sync --dev`
Expected: 安装依赖完成，无报错

- [ ] **Step 3: 跑后端测试集**

Run: `cd backend && ./.venv/bin/pytest ../tests/backend -v`
Expected: 全部通过

- [ ] **Step 4: 做真实启动验证**

Run: `cd backend && ./.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8011`
Expected: `/healthz` 返回 200，`/api/v1/check-requests/<uuid>` 返回 404 而不是 500
