# Backend Vue/React 采集完整性增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Vue/React 企业级 Web 系统补齐“页面发现高召回 + 状态探测高精度 + locator bundle 资产化”的正式后端链路，让采集结果更完整、资产更稳定、执行更可解释。

**Architecture:** 继续保持 `crawler_service -> asset_compiler -> runner_service` 主链不变。第一阶段不新增大量独立子域，而是优先扩展现有 crawl 事实模型与 extractor 分层：页面发现层负责多信号高召回找全页面与状态入口，状态探测层负责受控交互打开代表状态并产出带上下文的元素与定位证据；`asset_compiler` 把这些证据编译为 locator bundle 与状态感知 `module_plan`，`runner_service` 只按 bundle 确定性回放并记录 telemetry。

**Tech Stack:** FastAPI, Pydantic v2, SQLModel, Alembic, PostgreSQL, Redis, Playwright Python, pytest

---

## File Structure

**Files to Create:**

- `backend/src/app/domains/crawler_service/extractors/page_discovery.py`
  Responsibility: 聚合路由、导航骨架、网络/资源、可达性验证和状态入口信号，输出高召回页面候选与入口候选。
- `backend/src/app/domains/crawler_service/extractors/state_probe.py`
  Responsibility: 在单页面内执行受控白名单动作，生成 `state_signature`、状态上下文和带证据的元素候选。
- `backend/src/app/domains/asset_compiler/locator_bundles.py`
  Responsibility: 根据定位证据生成排序后的 locator bundle，并输出稳定性/特异性评分。
- `backend/alembic/versions/0011_crawl_state_and_locator_evidence.py`
  Responsibility: 为 crawl 事实层补齐状态上下文和 locator 证据字段。
- `tests/backend/test_page_discovery_extractor.py`
  Responsibility: 验证页面发现层的多信号归并、去重和入口标记。
- `tests/backend/test_state_probe_extractor.py`
  Responsibility: 验证受控状态探测、`state_signature` 去重和非破坏性动作预算。
- `tests/backend/test_locator_bundle_compiler.py`
  Responsibility: 验证 locator bundle 的排序、禁用策略过滤和上下文约束编译。

**Files to Modify:**

- `backend/src/app/domains/crawler_service/schemas.py`
  扩展页面、菜单、元素候选结构，增加状态上下文与定位证据字段。
- `backend/src/app/domains/crawler_service/service.py`
  重构 crawl 主流程，拆出页面发现层与状态探测层编排，并持久化增强后的事实。
- `backend/src/app/domains/crawler_service/extractors/router_runtime.py`
  扩展框架感知路由信号与 route hint 标准化逻辑。
- `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
  改造为导航骨架与基础入口信号提取，而不只生产单一 locator。
- `backend/src/app/infrastructure/db/models/crawl.py`
  为 `pages/menu_nodes/page_elements` 增加发现来源、状态上下文、locator 证据和上下文约束字段。
- `backend/src/app/domains/asset_compiler/schemas.py`
  扩展编译 DTO，支持 locator bundle 与状态上下文。
- `backend/src/app/domains/asset_compiler/fingerprints.py`
  将 locator bundle 和状态摘要纳入指纹摘要，避免只基于单一 locator。
- `backend/src/app/domains/asset_compiler/check_templates.py`
  为代表状态生成标准检查模板，例如 `open_create_modal`、`tab_switch_render`。
- `backend/src/app/domains/asset_compiler/module_plan_builder.py`
  生成带“进入状态上下文”步骤和 locator bundle 的 `module_plan`。
- `backend/src/app/domains/asset_compiler/service.py`
  把增强后的事实层编译为 `page_assets/page_checks/module_plans/asset_snapshots`。
- `backend/src/app/domains/runner_service/module_executor.py`
  支持 bundle 顺序回放、上下文约束判断和 fallback telemetry。
- `backend/src/app/domains/runner_service/playwright_runtime.py`
  增加进入状态上下文、按上下文容器定位元素、记录命中策略与失败原因的能力。
- `backend/src/app/domains/runner_service/service.py`
  将 locator 命中 telemetry 写回执行结果与 artifacts，供后续 recrawl/recompile 判断。
- `tests/backend/test_crawler_service.py`
  扩展 crawl 主流程集成测试。
- `tests/backend/test_asset_compiler_service.py`
  扩展状态感知编译、bundle 生成和指纹比较测试。
- `tests/backend/test_asset_fingerprints.py`
  扩展 bundle/状态摘要纳入指纹的稳定性测试。
- `tests/backend/test_runner_service.py`
  扩展 bundle 命中、fallback、上下文不匹配和 telemetry 持久化测试。
- `tests/backend/test_initial_schema.py`
  断言新增字段与迁移一致。
- `CHANGELOG.md`
  记录实施计划文档。

**Existing References to Read While Executing:**

- `docs/superpowers/specs/2026-04-03-backend-vue-react-crawl-completeness-design.md`
- `backend/src/app/domains/crawler_service/service.py`
- `backend/src/app/domains/crawler_service/extractors/router_runtime.py`
- `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
- `backend/src/app/domains/asset_compiler/service.py`
- `backend/src/app/domains/asset_compiler/module_plan_builder.py`
- `backend/src/app/domains/runner_service/service.py`
- `backend/src/app/domains/runner_service/playwright_runtime.py`
- `tests/backend/test_crawler_service.py`
- `docs/base_info.md`

---

### Task 1: 扩展采集事实契约并落库状态上下文与定位证据

**Files:**

- Create: `backend/alembic/versions/0011_crawl_state_and_locator_evidence.py`
- Modify: `backend/src/app/domains/crawler_service/schemas.py`
- Modify: `backend/src/app/infrastructure/db/models/crawl.py`
- Test: `tests/backend/test_initial_schema.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 先写失败测试，锁定增强后的事实契约**

```python
def test_page_element_schema_exposes_state_and_locator_candidates():
    from app.domains.crawler_service.schemas import ElementCandidate

    assert "state_signature" in ElementCandidate.model_fields
    assert "state_context" in ElementCandidate.model_fields
    assert "locator_candidates" in ElementCandidate.model_fields
```

```python
def test_page_elements_table_has_locator_candidates_and_state_context(inspector):
    columns = {column["name"] for column in inspector.get_columns("page_elements")}
    assert {"state_signature", "state_context", "locator_candidates"} <= columns
```

- [ ] **Step 2: 运行聚焦测试，确认当前契约确实缺失**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py ../tests/backend/test_crawler_service.py -v -k "state_context or locator_candidates"`
Expected: FAIL，因为当前 `ElementCandidate/PageElement` 还没有这些字段。

- [ ] **Step 3: 在 Pydantic 与 SQLModel 中补齐最小字段集**

```python
class ElementCandidate(BaseModel):
    page_route_path: str
    element_type: str
    state_signature: str | None = None
    state_context: dict[str, object] | None = None
    locator_candidates: list[dict[str, object]] = Field(default_factory=list)
```

```python
class PageElement(BaseModel, table=True):
    state_signature: str | None = Field(default=None, max_length=255)
    state_context: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    locator_candidates: list[dict[str, object]] | None = Field(default=None, sa_column=Column(JSON))
```

同样为 `Page/MenuNode` 增加最小必要字段：

- `discovery_sources`
- `entry_candidates`
- `context_constraints`

- [ ] **Step 4: 编写 Alembic 迁移并保持 metadata 对齐**

```python
op.add_column("pages", sa.Column("discovery_sources", sa.JSON(), nullable=True))
op.add_column("menu_nodes", sa.Column("locator_candidates", sa.JSON(), nullable=True))
op.add_column("page_elements", sa.Column("state_signature", sa.String(length=255), nullable=True))
```

不要引入额外表，第一阶段只扩展现有事实表，保持改动可控。

- [ ] **Step 5: 重新运行聚焦测试，确认契约与迁移通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_initial_schema.py ../tests/backend/test_crawler_service.py -v -k "state_context or locator_candidates"`
Expected: PASS

- [ ] **Step 6: 提交这一层契约变更**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/alembic/versions/0011_crawl_state_and_locator_evidence.py backend/src/app/domains/crawler_service/schemas.py backend/src/app/infrastructure/db/models/crawl.py tests/backend/test_initial_schema.py tests/backend/test_crawler_service.py
git commit -m "feat: add crawl state and locator evidence contracts"
```

---

### Task 2: 实现页面发现层，补齐多信号高召回页面与入口发现

**Files:**

- Create: `backend/src/app/domains/crawler_service/extractors/page_discovery.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/router_runtime.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Test: `tests/backend/test_page_discovery_extractor.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 先写失败测试，锁定页面发现层的信号归并行为**

```python
@pytest.mark.anyio
async def test_page_discovery_merges_route_nav_and_network_signals():
    extractor = PageDiscoveryExtractor()
    result = await extractor.extract(browser_session=FakeDiscoverySession(), system=None, crawl_scope="full")

    assert {page.route_path for page in result.pages} >= {"/dashboard", "/users", "/reports"}
    assert any("network_route_config" in page.discovery_sources for page in result.pages)
```

```python
@pytest.mark.anyio
async def test_page_discovery_marks_tabs_and_modal_triggers_as_entry_candidates():
    result = await PageDiscoveryExtractor().extract(
        browser_session=FakeDiscoverySession(),
        system=None,
        crawl_scope="full",
    )

    users_page = next(page for page in result.pages if page.route_path == "/users")
    assert {"tab_switch", "open_modal"} <= {entry["entry_type"] for entry in users_page.entry_candidates}
```

- [ ] **Step 2: 运行聚焦测试，确认页面发现层尚不存在**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_page_discovery_extractor.py ../tests/backend/test_crawler_service.py -v -k "page_discovery"`
Expected: FAIL，因为 `PageDiscoveryExtractor` 及相关字段尚未实现。

- [ ] **Step 3: 实现页面发现层并保持职责单一**

```python
class PageDiscoveryExtractor:
    async def extract(self, *, browser_session, system, crawl_scope: str) -> CrawlExtractionResult:
        route_pages = await self._collect_route_pages(browser_session=browser_session)
        nav_pages = await self._collect_navigation_pages(browser_session=browser_session)
        network_pages = await self._collect_network_pages(browser_session=browser_session)
        pages = self._merge_pages(route_pages, nav_pages, network_pages)
        return CrawlExtractionResult(pages=pages, quality_score=self._score_pages(pages))
```

在该 extractor 内完成以下约束：

- 路由信号、导航骨架信号、网络/资源信号分别采集
- 先做 route 级去重，再合并发现来源
- 对候选路径做轻量可达性验证，但不在这里执行深层交互
- 将 Tabs、弹窗按钮、抽屉按钮、筛选展开等入口只标记为 `entry_candidates`

- [ ] **Step 4: 让 `CrawlerService` 使用页面发现层而不是直接拼装零散结果**

```python
discovery_result = await self.page_discovery_extractor.extract(
    browser_session=browser_session,
    system=system,
    crawl_scope=crawl_scope,
)
```

`CrawlerService._combine_results()` 需改成“页面发现结果 + 状态探测结果”的合并逻辑，不再假定 `runtime + dom` 就是全部真相。

- [ ] **Step 5: 重新运行聚焦测试，确认页面发现层通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_page_discovery_extractor.py ../tests/backend/test_crawler_service.py -v -k "page_discovery"`
Expected: PASS

- [ ] **Step 6: 提交页面发现层**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/crawler_service/extractors/page_discovery.py backend/src/app/domains/crawler_service/extractors/router_runtime.py backend/src/app/domains/crawler_service/extractors/dom_menu.py backend/src/app/domains/crawler_service/service.py tests/backend/test_page_discovery_extractor.py tests/backend/test_crawler_service.py
git commit -m "feat: add high-recall page discovery extractor"
```

---

### Task 3: 实现受控状态探测层，补齐代表状态与状态化元素

**Files:**

- Create: `backend/src/app/domains/crawler_service/extractors/state_probe.py`
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Modify: `backend/src/app/domains/crawler_service/schemas.py`
- Test: `tests/backend/test_state_probe_extractor.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 先写失败测试，锁定状态探测白名单、预算与去重**

```python
@pytest.mark.anyio
async def test_state_probe_collects_representative_states_without_unsafe_actions():
    extractor = ControlledStateProbeExtractor()
    result = await extractor.extract(browser_session=FakeStateProbeSession(), system=None, crawl_scope="full")

    assert {element.state_signature for element in result.elements} >= {
        "users:default",
        "users:tab=disabled",
        "users:modal=create",
    }
    assert "submit_form" not in FakeStateProbeSession.performed_actions
```

```python
@pytest.mark.anyio
async def test_state_probe_stops_when_interaction_budget_is_exhausted():
    result = await ControlledStateProbeExtractor(max_actions_per_page=2).extract(
        browser_session=FakeStateProbeSession(),
        system=None,
        crawl_scope="full",
    )

    assert "interaction_budget_exhausted" in result.warning_messages
```

- [ ] **Step 2: 运行聚焦测试，确认状态探测层尚未实现**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_state_probe_extractor.py ../tests/backend/test_crawler_service.py -v -k "state_probe or interaction_budget"`
Expected: FAIL，因为 `ControlledStateProbeExtractor` 尚不存在。

- [ ] **Step 3: 实现受控动作白名单和状态签名生成**

```python
ALLOWED_ACTIONS = {
    "tab_switch",
    "expand_panel",
    "open_modal",
    "open_drawer",
    "toggle_view",
    "paginate_probe",
    "tree_expand",
}
```

```python
def build_state_signature(route_path: str, state_context: dict[str, object]) -> str:
    parts = [route_path.strip("/").replace("/", ":") or "root"]
    if state_context.get("active_tab"):
        parts.append(f"tab={state_context['active_tab']}")
    if state_context.get("modal_title"):
        parts.append(f"modal={state_context['modal_title']}")
    return ":".join(parts)
```

要求：

- 所有交互都先判断 `entry_type` 是否在白名单内
- 对同一 `state_signature` 去重
- 只对代表状态落元素事实
- 将 `blocked_by_permission`、`unsafe_action_rejected`、`interaction_budget_exhausted` 作为结构化 warning/failure 写回

- [ ] **Step 4: 把状态探测结果整合进 crawl 主流程**

```python
probe_result = await self.state_probe_extractor.extract(
    browser_session=browser_session,
    system=system,
    crawl_scope=crawl_scope,
)
combined = self._combine_results(discovery=discovery_result, probe=probe_result, system=system)
```

`_persist_elements()` 需要把 `state_signature/state_context/locator_candidates` 一并写入。

- [ ] **Step 5: 重新运行聚焦测试，确认状态探测通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_state_probe_extractor.py ../tests/backend/test_crawler_service.py -v -k "state_probe or interaction_budget"`
Expected: PASS

- [ ] **Step 6: 提交状态探测层**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/crawler_service/extractors/state_probe.py backend/src/app/domains/crawler_service/service.py backend/src/app/domains/crawler_service/schemas.py tests/backend/test_state_probe_extractor.py tests/backend/test_crawler_service.py
git commit -m "feat: add controlled state probe extractor"
```

---

### Task 4: 在 asset_compiler 中编译 locator bundle 与状态感知 module plan

**Files:**

- Create: `backend/src/app/domains/asset_compiler/locator_bundles.py`
- Modify: `backend/src/app/domains/asset_compiler/schemas.py`
- Modify: `backend/src/app/domains/asset_compiler/fingerprints.py`
- Modify: `backend/src/app/domains/asset_compiler/check_templates.py`
- Modify: `backend/src/app/domains/asset_compiler/module_plan_builder.py`
- Modify: `backend/src/app/domains/asset_compiler/service.py`
- Test: `tests/backend/test_locator_bundle_compiler.py`
- Test: `tests/backend/test_asset_fingerprints.py`
- Test: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: 先写失败测试，锁定 bundle 排序与禁用策略**

```python
def test_compile_locator_bundle_prefers_semantic_then_label_then_testid():
    bundle = build_locator_bundle(
        locator_candidates=[
            {"strategy_type": "css", "selector": ".btn.btn-primary"},
            {"strategy_type": "semantic", "selector": "role=button[name='新增用户']"},
            {"strategy_type": "label", "selector": "label=新增用户"},
        ],
        state_context={"modal_title": "新增用户"},
    )

    assert [item["strategy_type"] for item in bundle.candidates[:3]] == ["semantic", "label", "css"]
```

```python
def test_build_page_fingerprint_uses_locator_bundle_summary_instead_of_single_locator():
    fingerprint = build_page_fingerprint(
        {
            "route_path": "/users",
            "elements": [
                {
                    "state_signature": "users:default",
                    "locator_bundle": {"candidates": [{"strategy_type": "semantic", "selector": "role=button[name='新增用户']"}]},
                }
            ],
        }
    )

    assert fingerprint["key_locator_hash"]
```

- [ ] **Step 2: 运行聚焦测试，确认 bundle 编译逻辑尚不存在**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_locator_bundle_compiler.py ../tests/backend/test_asset_fingerprints.py ../tests/backend/test_asset_compiler_service.py -v -k "locator_bundle or key_locator_hash"`
Expected: FAIL，因为当前仍只依赖单一 `playwright_locator`。

- [ ] **Step 3: 实现 locator bundle 编译器**

```python
STRATEGY_PRIORITY = {
    "semantic": 100,
    "label": 90,
    "testid": 80,
    "text_anchor": 70,
    "structure": 60,
    "css": 10,
}
```

```python
def build_locator_bundle(*, locator_candidates, state_context):
    filtered = [item for item in locator_candidates if not _is_forbidden_locator(item)]
    ranked = sorted(filtered, key=_rank_locator_candidate, reverse=True)
    return LocatorBundle(candidates=[_attach_context(item, state_context) for item in ranked])
```

明确禁止：

- 动态 ID
- 纯 `nth-child`
- 过长 class 链
- hash class

- [ ] **Step 4: 让 `asset_compiler` 生成状态感知 `module_plan`**

```python
if state_signature and state_signature != default_state_signature:
    steps.append({"module": "state.enter", "params": {"state_signature": state_signature}})
steps.append({"module": "locator.assert", "params": {"locator_bundle": bundle.model_dump()}})
```

同时调整标准检查模板，使以下能力可编译：

- 默认列表页 `page_open/table_render`
- 代表性 Tab 状态渲染检查
- 新增弹窗打开检查

- [ ] **Step 5: 重新运行聚焦测试，确认 bundle 与编译通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_locator_bundle_compiler.py ../tests/backend/test_asset_fingerprints.py ../tests/backend/test_asset_compiler_service.py -v -k "locator_bundle or state_signature or key_locator_hash"`
Expected: PASS

- [ ] **Step 6: 提交 locator bundle 与状态化编译**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/locator_bundles.py backend/src/app/domains/asset_compiler/schemas.py backend/src/app/domains/asset_compiler/fingerprints.py backend/src/app/domains/asset_compiler/check_templates.py backend/src/app/domains/asset_compiler/module_plan_builder.py backend/src/app/domains/asset_compiler/service.py tests/backend/test_locator_bundle_compiler.py tests/backend/test_asset_fingerprints.py tests/backend/test_asset_compiler_service.py
git commit -m "feat: compile locator bundles and state-aware module plans"
```

---

### Task 5: 在 runner_service 中确定性回放 locator bundle 并落 telemetry

**Files:**

- Modify: `backend/src/app/domains/runner_service/module_executor.py`
- Modify: `backend/src/app/domains/runner_service/playwright_runtime.py`
- Modify: `backend/src/app/domains/runner_service/service.py`
- Test: `tests/backend/test_runner_service.py`

- [ ] **Step 1: 先写失败测试，锁定主定位命中、fallback 命中和上下文不匹配行为**

```python
@pytest.mark.anyio
async def test_runner_uses_primary_locator_before_fallback(runner_service, seeded_stateful_check):
    result = await runner_service.run_page_check(page_check_id=seeded_stateful_check.id)

    assert result.artifact_payload["locator_match"]["matched_rank"] == 1
    assert result.artifact_payload["locator_match"]["strategy_type"] == "semantic"
```

```python
@pytest.mark.anyio
async def test_runner_records_context_mismatch_when_modal_state_is_missing(runner_service, seeded_modal_check):
    result = await runner_service.run_page_check(page_check_id=seeded_modal_check.id)

    assert result.failure_category == "context_mismatch"
```

- [ ] **Step 2: 运行聚焦测试，确认当前 runtime 只支持单一 locator**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_runner_service.py -v -k "matched_rank or context_mismatch or strategy_type"`
Expected: FAIL，因为当前 runtime 还不会按 bundle 顺序回放，也不会记录 telemetry。

- [ ] **Step 3: 为 runtime 和 module executor 增加 bundle 回放协议**

```python
class RunnerRuntime(Protocol):
    async def resolve_locator_bundle(
        self,
        *,
        locator_bundle: dict[str, object],
        context_constraints: dict[str, object] | None,
    ) -> LocatorMatchResult: ...
```

```python
match = await self.runtime.resolve_locator_bundle(
    locator_bundle=params["locator_bundle"],
    context_constraints=params.get("context_constraints"),
)
if not match.matched:
    raise ModuleExecutionError(match.failure_category)
```

要求：

- 只按 bundle 顺序尝试候选
- 成功即停止
- 不允许运行时发明新 selector
- 将 `matched_rank/strategy_type/failure_category` 写入 step 结果

- [ ] **Step 4: 将 bundle telemetry 持久化到执行结果与 artifacts**

```python
artifact_payload = {
    "locator_match": {
        "matched_rank": match.matched_rank,
        "strategy_type": match.strategy_type,
        "failure_category": match.failure_category,
    }
}
```

把以下信息统一写回：

- `locator_primary_hit`
- `locator_fallback_used`
- `matched_rank`
- `context_mismatch`
- `ambiguous_match`

- [ ] **Step 5: 重新运行聚焦测试，确认 runtime 通过**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_runner_service.py -v -k "matched_rank or context_mismatch or strategy_type"`
Expected: PASS

- [ ] **Step 6: 提交 runner bundle 回放与 telemetry**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/runner_service/module_executor.py backend/src/app/domains/runner_service/playwright_runtime.py backend/src/app/domains/runner_service/service.py tests/backend/test_runner_service.py
git commit -m "feat: add locator bundle playback telemetry"
```

---

### Task 6: 收口回归验证、指标基线与文档记录

**Files:**

- Modify: `tests/backend/test_crawler_service.py`
- Modify: `tests/backend/test_asset_compiler_service.py`
- Modify: `tests/backend/test_runner_service.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 先补失败测试，锁定第一阶段基线**

```python
@pytest.mark.anyio
async def test_crawl_compile_run_chain_preserves_state_signature_and_locator_bundle(
    crawler_service,
    asset_compiler_service,
    runner_service,
):
    crawl_result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")
    compile_result = await asset_compiler_service.compile_snapshot(snapshot_id=crawl_result.snapshot_id)

    assert compile_result.page_assets_created >= 1
    assert compile_result.checks_created >= 1
```

```python
def test_plan_first_stage_acceptance_thresholds_are_documented():
    thresholds = {
        "main_nav_coverage": 0.95,
        "representative_state_coverage": 0.80,
        "key_element_precision": 0.90,
        "primary_locator_hit_rate": 0.85,
    }
    assert thresholds["main_nav_coverage"] == 0.95
```

第二个测试只是锁定常量位置，便于后续把指标计算抽成代码时有稳定入口。

- [ ] **Step 2: 运行聚焦回归，确认链路尚未完全闭合**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_crawler_service.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_runner_service.py -v -k "state_signature or locator_bundle or primary_locator_hit_rate"`
Expected: FAIL，直到 crawl -> compile -> run 三段都完成增强。

- [ ] **Step 3: 补齐最小指标基线与回归断言**

实现时至少保证测试里能验证：

- crawl 结果已包含 `state_signature/locator_candidates`
- compile 结果已生成 locator bundle 和状态进入步骤
- runner 结果已记录主定位命中或 fallback 命中

如果需要统计常量位置，优先放到现有 schema/telemetry 结构中，不要额外引入新服务。

- [ ] **Step 4: 重新运行完整后端回归**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run pytest ../tests/backend/test_crawler_service.py ../tests/backend/test_page_discovery_extractor.py ../tests/backend/test_state_probe_extractor.py ../tests/backend/test_locator_bundle_compiler.py ../tests/backend/test_asset_compiler_service.py ../tests/backend/test_asset_fingerprints.py ../tests/backend/test_runner_service.py ../tests/backend/test_initial_schema.py -v`
Expected: PASS

然后执行一次真实数据库迁移冒烟：

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run alembic upgrade head`
Expected: 成功升级到最新 revision，无额外 head 分叉。

- [ ] **Step 5: 更新 `CHANGELOG.md` 并提交收口**

```bash
cd /Users/wangpei/src/singe/Runlet
git add tests/backend/test_crawler_service.py tests/backend/test_asset_compiler_service.py tests/backend/test_runner_service.py CHANGELOG.md
git commit -m "test: add crawl completeness regression coverage"
```

---

## Execution Notes

- 实施时严格遵守 TDD：先写失败测试，再补最小实现，再跑聚焦测试，再提交。
- 如果发现 `0011` 迁移号已被占用，先查看当前 head，再顺延 revision 编号，不能强行复用。
- 如真实站点验证需要使用 `docs/base_info.md` 中的系统，请把它们作为手工验收，不要把真实凭据硬编码进测试。
- `runner_service` 必须继续以 `module_plan` 为正式执行真相，不能因 locator bundle 引入 runtime improvisation。
- 任何新增字段如果只作为中间态调试信息且不会被编译或执行消费，不要入库。
