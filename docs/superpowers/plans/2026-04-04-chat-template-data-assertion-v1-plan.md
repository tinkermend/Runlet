# Chat Template Data Assertion V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为企业内部 Vue/React 管理平台交付“模板优先”的只读数据断言闭环，支持 AI Chat 候选推荐、参数化执行、table/list 场景断言与调度沉淀。

**Architecture:** 保持 `skills -> control_plane -> asset_compiler -> runner_service` 主链不变；通过模板注册中心、执行请求参数持久化和受控模块扩展实现动态数据断言。Chat/Web 入口统一落到同一后端契约，执行真相仍为 `page_check + module_plan + runtime_policy`。

**Tech Stack:** FastAPI, Pydantic v2, SQLModel, Alembic, PostgreSQL/SQLite(test), Playwright Python, pytest

---

## 实施约束

- 全流程遵循 `@test-driven-development`：先写失败测试，再最小实现。
- 每个任务结束前执行 `@verification-before-completion` 的验证命令。
- 仅实现 V1 只读范围：`table/list`，不新增 `detail` carrier。
- 每个任务独立提交，保持小步可回滚。

---

## File Structure

**Files to Create:**

- `backend/src/app/domains/control_plane/recommendation.py`
  - 候选评分与排序策略（成功率优先、冷启动回退）。
- `backend/src/app/domains/asset_compiler/template_registry.py`
  - V1 模板注册中心与模板契约。
- `backend/src/app/domains/runner_service/data_assertion_modules.py`
  - table/list 数据断言运行时辅助（计数、字段命中、空态识别）。
- `backend/alembic/versions/0012_execution_request_template_params.py`
  - 执行请求模板参数字段迁移。
- `tests/backend/test_check_candidates_api.py`
  - `check candidate` API 覆盖。
- `tests/backend/test_template_registry.py`
  - 模板注册与模块计划编译覆盖。

**Files to Modify:**

- `backend/src/app/domains/control_plane/schemas.py`
  - 扩展 `CreateCheckRequest`（模板元数据与参数）；新增候选请求/响应 DTO。
- `backend/src/app/domains/control_plane/repository.py`
  - 持久化模板参数字段；新增候选查询与历史统计查询。
- `backend/src/app/domains/control_plane/service.py`
  - 模板参数校验、只读守卫、候选推荐入口。
- `backend/src/app/api/endpoints/check_requests.py`
  - 新增 `POST /api/v1/check-requests:candidates`。
- `backend/src/app/infrastructure/db/models/execution.py`
  - `execution_requests` 增加模板字段。
- `backend/src/app/domains/asset_compiler/check_templates.py`
  - 改为模板注册驱动生成标准检查。
- `backend/src/app/domains/asset_compiler/module_plan_builder.py`
  - 生成 V1 模板模块链（过滤、查询、断言）。
- `backend/src/app/domains/asset_compiler/schemas.py`
  - 补模板定义与计划草案参数占位支持。
- `backend/src/app/domains/runner_service/module_executor.py`
  - 增加 `action.apply_filter/action.submit_query/assert.data_count/assert.row_exists_by_field`。
- `backend/src/app/domains/runner_service/playwright_runtime.py`
  - 运行时输入、搜索触发、table/list 抽象断言实现。
- `backend/src/app/domains/runner_service/service.py`
  - 执行时注入 `template_params` 到模块执行上下文。
- `backend/src/app/jobs/run_check_job.py`
  - 把 execution request 中的模板参数透传到 runner。
- `tests/backend/test_check_requests_api.py`
  - 请求契约与模板参数校验回归。
- `tests/backend/test_control_plane_service.py`
  - 候选排序、只读守卫、参数边界回归。
- `tests/backend/test_asset_compiler_service.py`
  - 模板编译与 module_plan 产出回归。
- `tests/backend/test_runner_service.py`
  - 新增数据断言模块运行回归。
- `tests/backend/test_run_check_job.py`
  - 模板参数透传与结果回写回归。
- `tests/backend/test_initial_schema.py`
  - 新字段与迁移后 schema 对齐。
- `CHANGELOG.md`
  - 记录本计划的设计/实施变更。

---

### Task 1: 扩展检查请求契约（模板参数 + 载体）

**Files:**
- Modify: `backend/src/app/domains/control_plane/schemas.py`
- Modify: `backend/src/app/api/endpoints/check_requests.py`
- Test: `tests/backend/test_check_requests_api.py`

- [ ] **Step 1: 先写失败测试（请求支持模板字段）**

```python
def test_post_check_requests_accepts_template_payload(client):
    response = client.post(
        "/api/v1/check-requests",
        json={
            "system_hint": "ERP",
            "page_hint": "用户管理",
            "check_goal": "field_equals_exists",
            "template_code": "field_equals_exists",
            "template_version": "v1",
            "carrier_hint": "table",
            "template_params": {"field": "username", "operator": "equals", "value": "alice"},
        },
    )
    assert response.status_code == 202
```

- [ ] **Step 2: 运行用例确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_check_requests_api.py -v -k "template_payload"`
Expected: FAIL，提示 schema 不接受新字段或被忽略。

- [ ] **Step 3: 最小实现 DTO 与 API 透传**

```python
class CreateCheckRequest(BaseModel):
    ...
    template_code: str | None = None
    template_version: str | None = None
    carrier_hint: Literal["table", "list"] | None = None
    template_params: dict[str, object] | None = None
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_check_requests_api.py -v -k "template_payload"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/schemas.py backend/src/app/api/endpoints/check_requests.py tests/backend/test_check_requests_api.py
git commit -m "feat: extend check request contract for template params"
```

---

### Task 2: 持久化模板参数到 execution request

**Files:**
- Modify: `backend/src/app/infrastructure/db/models/execution.py`
- Create: `backend/alembic/versions/0012_execution_request_template_params.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Test: `tests/backend/test_initial_schema.py`
- Test: `tests/backend/test_control_plane_service.py`

- [ ] **Step 1: 写失败测试（schema 必含新列）**

```python
def test_execution_requests_table_contains_template_columns(inspector):
    columns = {column["name"] for column in inspector.get_columns("execution_requests")}
    assert {"template_code", "template_version", "carrier_hint", "template_params"} <= columns
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py -v -k "template_columns"`
Expected: FAIL，列不存在。

- [ ] **Step 3: 添加 model + migration + repository 入库逻辑**

```python
class ExecutionRequest(BaseModel, table=True):
    ...
    template_code: str | None = Field(default=None, max_length=64)
    template_version: str | None = Field(default=None, max_length=32)
    carrier_hint: str | None = Field(default=None, max_length=16)
    template_params: dict[str, object] | None = Field(default=None, sa_column=sa.Column(json_type, nullable=True))
```

- [ ] **Step 4: 验证迁移与服务测试通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py ../tests/backend/test_control_plane_service.py -v -k "template"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/infrastructure/db/models/execution.py backend/alembic/versions/0012_execution_request_template_params.py backend/src/app/domains/control_plane/repository.py tests/backend/test_initial_schema.py tests/backend/test_control_plane_service.py
git commit -m "feat: persist template metadata in execution requests"
```

---

### Task 3: 候选推荐 API（成功率优先 + 冷启动回退）

**Files:**
- Create: `backend/src/app/domains/control_plane/recommendation.py`
- Modify: `backend/src/app/domains/control_plane/schemas.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/api/endpoints/check_requests.py`
- Create: `tests/backend/test_check_candidates_api.py`
- Modify: `tests/backend/test_control_plane_service.py`

- [ ] **Step 1: 先写 API 失败测试（返回 2-3 候选）**

```python
def test_post_check_request_candidates_returns_ranked_candidates(client):
    response = client.post(
        "/api/v1/check-requests:candidates",
        json={
            "system_hint": "ERP",
            "page_hint": "用户管理",
            "intent": "查询用户名 alice 是否存在",
            "slot_hints": {"field": "username", "value": "alice"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body["candidates"]) <= 3
    assert body["candidates"][0]["rank_score"] >= body["candidates"][-1]["rank_score"]
```

- [ ] **Step 2: 跑失败测试**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_check_candidates_api.py -v`
Expected: FAIL，路由不存在。

- [ ] **Step 3: 实现服务与排序策略**

```python
rank_score = (
    success_rate_weight * success_rate
    + confidence_weight * alias_confidence
    + recency_weight * recency_score
)
```

冷启动规则：样本数 `< 20` 时优先 alias confidence，再回退最近使用。

- [ ] **Step 4: 跑 API + service 用例**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_check_candidates_api.py ../tests/backend/test_control_plane_service.py -v -k "candidate"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/recommendation.py backend/src/app/domains/control_plane/schemas.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/service.py backend/src/app/api/endpoints/check_requests.py tests/backend/test_check_candidates_api.py tests/backend/test_control_plane_service.py
git commit -m "feat: add check candidate recommendation api"
```

---

### Task 4: 模板注册中心与 V1 module plan 编译（5 模板全覆盖）

**Files:**
- Create: `backend/src/app/domains/asset_compiler/template_registry.py`
- Modify: `backend/src/app/domains/asset_compiler/schemas.py`
- Modify: `backend/src/app/domains/asset_compiler/check_templates.py`
- Modify: `backend/src/app/domains/asset_compiler/module_plan_builder.py`
- Create: `tests/backend/test_template_registry.py`
- Modify: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: 写失败测试（V1 模板集与 module plan）**

```python
def test_template_registry_contains_v1_readonly_templates():
    from app.domains.asset_compiler.template_registry import list_templates
    template_codes = {item.template_code for item in list_templates(version="v1")}
    assert template_codes == {
        "has_data",
        "no_data",
        "field_equals_exists",
        "status_exists",
        "count_gte",
    }
```

```python
def test_build_module_plan_for_field_equals_exists_uses_query_assert_chain():
    plan = build_module_plan(
        check_code="field_equals_exists",
        page_context={"route_path": "/users", "menu_chain": ["系统管理", "用户管理"]},
        locator_bundle={"candidates": []},
    )
    assert [step["module"] for step in plan.steps_json][-3:] == [
        "action.apply_filter",
        "action.submit_query",
        "assert.row_exists_by_field",
    ]
```

```python
def test_build_module_plan_for_count_gte_uses_data_count_assert():
    plan = build_module_plan(
        check_code="count_gte",
        page_context={"route_path": "/users", "menu_chain": ["系统管理", "用户管理"]},
        locator_bundle={"candidates": []},
    )
    assert plan.steps_json[-1]["module"] == "assert.data_count"
```

- [ ] **Step 2: 运行失败测试**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_template_registry.py ../tests/backend/test_asset_compiler_service.py -v -k "field_equals_exists or template_registry"`
Expected: FAIL。

- [ ] **Step 3: 实现模板注册与编译映射**

```python
@dataclass(frozen=True)
class TemplateDefinition:
    template_code: str
    template_version: str
    supported_carriers: set[str]
    required_slots: tuple[str, ...]
    assertion_contract: dict[str, object]
    compile_strategy: dict[str, object]
    readonly: bool
```

- [ ] **Step 4: 运行编译相关测试**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_template_registry.py ../tests/backend/test_asset_compiler_service.py -v -k "template or module_plan or count_gte or status_exists"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/template_registry.py backend/src/app/domains/asset_compiler/schemas.py backend/src/app/domains/asset_compiler/check_templates.py backend/src/app/domains/asset_compiler/module_plan_builder.py tests/backend/test_template_registry.py tests/backend/test_asset_compiler_service.py
git commit -m "feat: add v1 template registry and plan compilation"
```

---

### Task 5: Runner 支持数据断言模块（table/list，覆盖 5 模板断言）

**Files:**
- Create: `backend/src/app/domains/runner_service/data_assertion_modules.py`
- Modify: `backend/src/app/domains/runner_service/module_executor.py`
- Modify: `backend/src/app/domains/runner_service/playwright_runtime.py`
- Modify: `backend/src/app/domains/runner_service/service.py`
- Modify: `tests/backend/test_runner_service.py`

- [ ] **Step 1: 写失败测试（新模块链可执行）**

```python
@pytest.mark.anyio
async def test_run_page_check_supports_field_equals_exists_module_chain(runner_service, seeded_ready_check):
    result = await runner_service.run_page_check(page_check_id=seeded_ready_check.id)
    modules = [step.module for step in result.step_results]
    assert "action.apply_filter" in modules
    assert "assert.row_exists_by_field" in modules
```

```python
@pytest.mark.anyio
async def test_run_page_check_supports_no_data_and_count_gte_assertions(...):
    ...
    assert "assert.data_count" in modules
```

```python
@pytest.mark.anyio
async def test_run_page_check_supports_status_exists_assertion(...):
    ...
    assert "assert.row_exists_by_field" in modules
```

- [ ] **Step 2: 跑失败测试**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_runner_service.py -v -k "field_equals_exists or data_count or status_exists or no_data"`
Expected: FAIL，`unsupported module`。

- [ ] **Step 3: 最小实现 runtime 与 executor 分支**

```python
elif module == "assert.data_count":
    count = await self.runtime.read_data_count(carrier=_optional_text(params.get("carrier")) or "table")
    expected = int(params.get("expected_min") or 1)
    if count < expected:
        raise ValueError("data_count_assertion_failed")
```

- [ ] **Step 4: 运行 runner 回归**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_runner_service.py -v -k "data_count or row_exists or apply_filter or no_data or status_exists"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/runner_service/data_assertion_modules.py backend/src/app/domains/runner_service/module_executor.py backend/src/app/domains/runner_service/playwright_runtime.py backend/src/app/domains/runner_service/service.py tests/backend/test_runner_service.py
git commit -m "feat: add table list data assertion runtime modules"
```

---

### Task 6: 参数透传、只读守卫与作业执行闭环

**Files:**
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `backend/src/app/jobs/run_check_job.py`
- Modify: `backend/src/app/domains/runner_service/service.py`
- Modify: `tests/backend/test_control_plane_service.py`
- Modify: `tests/backend/test_run_check_job.py`

- [ ] **Step 1: 写失败测试（模板参数透传到 runner）**

```python
@pytest.mark.anyio
async def test_run_check_job_passes_template_params_to_runner(...):
    ...
    assert refreshed.result_payload["status"] == "passed"
    assert refreshed.result_payload["execution_track"] == "precompiled"
```

```python
@pytest.mark.anyio
async def test_submit_check_request_rejects_non_readonly_template_action(control_plane_service):
    with pytest.raises(HTTPException, match="readonly template required"):
        await control_plane_service.submit_check_request(
            system_hint="ERP",
            page_hint="用户管理",
            check_goal="delete_resource",
            template_code="delete_resource",
        )
```

```python
@pytest.mark.anyio
async def test_submit_check_request_returns_element_asset_missing_for_template_when_page_resolved(...):
    with pytest.raises(HTTPException, match="element asset is missing"):
        await control_plane_service.submit_check_request(
            system_hint="WMS",
            page_hint="库存列表",
            check_goal="field_equals_exists",
            template_code="field_equals_exists",
            template_version="v1",
            carrier_hint="table",
            template_params={"field": "username", "operator": "equals", "value": "alice"},
        )
```

- [ ] **Step 2: 跑失败测试**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_job.py ../tests/backend/test_control_plane_service.py -v -k "template_params or readonly or element_asset_missing"`
Expected: FAIL。

- [ ] **Step 3: 实现透传与守卫**

```python
result = await self.runner_service.run_page_check(
    page_check_id=parsed_page_check_id,
    execution_plan_id=parsed_execution_plan_id,
    runtime_inputs=request.template_params or {},
)
```

- [ ] **Step 4: 运行闭环测试**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_run_check_job.py ../tests/backend/test_control_plane_service.py -v -k "template or readonly or element_asset_missing"`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/service.py backend/src/app/jobs/run_check_job.py backend/src/app/domains/runner_service/service.py tests/backend/test_control_plane_service.py tests/backend/test_run_check_job.py
git commit -m "feat: enforce readonly templates and pass runtime inputs"
```

---

### Task 7: 文档、变更记录与最终验证

**Files:**
- Modify: `CHANGELOG.md`
- Optional Modify: `backend/README.md`（若新增 API 需补文档）

- [ ] **Step 1: 更新变更记录**

```markdown
- 新增模板化数据断言 V1：候选推荐 API、模板参数持久化、table/list 数据断言模块与只读守卫。
```

- [ ] **Step 2: 运行核心回归矩阵**

Run:
`cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_check_requests_api.py ../tests/backend/test_check_candidates_api.py ../tests/backend/test_control_plane_service.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_template_registry.py ../tests/backend/test_runner_service.py ../tests/backend/test_run_check_job.py ../tests/backend/test_initial_schema.py -v`

Expected: PASS。

- [ ] **Step 3: 提交收口**

```bash
cd /Users/wangpei/src/singe/Runlet
git add CHANGELOG.md backend/README.md
git commit -m "docs: finalize template data assertion v1 rollout notes"
```

---

## 分阶段里程碑（与 spec 一致）

1. **M1（契约完成）**：模板请求字段 + 候选 API 可用。
2. **M2（执行完成）**：table/list 的 `has_data/no_data/field_equals_exists/status_exists/count_gte` 跑通。
3. **M3（治理完成）**：只读守卫、统计排序、回归矩阵全绿。

---

## 风险检查清单

- 是否错误引入 `detail` carrier（V1 禁止）
- 是否引入写操作模块（V1 禁止）
- 是否绕过 `control_plane` 直接执行（禁止）
- 是否在无测试情况下修改模板编译与 runner 核心路径（禁止）
