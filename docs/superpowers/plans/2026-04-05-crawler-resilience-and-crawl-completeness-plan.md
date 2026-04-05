# Crawler Resilience And Crawl Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `crawler_service` 建立通用的登录后路由解析、页面稳定化、导航展开与状态探测主链，显著提升菜单、页面、元素事实的采集完整度，并以 `HotGo` 作为验证样本而非专属逻辑来源。

**Architecture:** 实现采用 `会话稳定化 -> 导航图扩展 -> 页面访问与状态探测` 三段式主链。通过新增 `resolved_route`、`NavigationTarget`、菜单 materialize 与失败分级，把当前依赖瞬时 DOM 快照的采集路径重构为可诊断、可预算、可测试的采集引擎，同时保持 `asset_compiler` 继续只消费事实层结果。

**Tech Stack:** FastAPI, Pydantic v2, SQLModel, Alembic, Playwright Python, pytest

---

## 文件结构

### 新增文件

- `backend/src/app/domains/crawler_service/extractors/route_resolution.py`
  负责统一 `pathname/hash/router/history` 到 `resolved_route`，并提供路由归一化与来源标注。
- `backend/src/app/domains/crawler_service/extractors/app_readiness.py`
  负责 `shell_ready/route_ready/content_ready` 判定与登录后收敛窗口逻辑。
- `backend/src/app/domains/crawler_service/navigation_targets.py`
  负责 `NavigationTarget`、去重键、预算分类与 materialization 状态定义。
- `tests/backend/test_route_resolution.py`
  覆盖 hash route、runtime router、history state 的路由解析回归。
- `tests/backend/test_navigation_targets.py`
  覆盖导航目标去重、预算、父子关系和失败分级。
- `backend/alembic/versions/0014_crawl_navigation_materialization_metadata.py`
  为页面、元素、快照补充采集诊断与 materialize 元数据字段。

### 重点修改文件

- `backend/src/app/domains/crawler_service/service.py`
  重构 Playwright 会话、路由采样、页面稳定化、菜单展开和状态探测编排。
- `backend/src/app/domains/crawler_service/schemas.py`
  扩展 warning / failure reason、导航目标与结果上下文字段。
- `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
  从静态 DOM 菜单读取升级为菜单骨架发现与局部重扫。
- `backend/src/app/domains/crawler_service/extractors/page_discovery.py`
  改为消费 `NavigationTarget` 与 `resolved_route`，区分页入口和状态入口。
- `backend/src/app/domains/crawler_service/extractors/state_probe.py`
  改为消费页面访问后的状态目标队列，输出可诊断失败原因。
- `backend/src/app/infrastructure/db/models/crawl.py`
  为页面、元素、快照补充最小必要的采集诊断字段。
- `backend/src/app/domains/asset_compiler/service.py`
  保持对新增事实字段的兼容读取，不改变编译主职责。

### 已有测试文件

- `tests/backend/test_crawler_service.py`
- `tests/backend/test_state_probe_extractor.py`
- `tests/backend/test_page_discovery_extractor.py`
- `tests/backend/test_asset_compiler_service.py`
- `tests/backend/test_initial_schema.py`

---

### Task 1: 路由解析与页面稳定化底座

**Files:**
- Create: `backend/src/app/domains/crawler_service/extractors/route_resolution.py`
- Create: `backend/src/app/domains/crawler_service/extractors/app_readiness.py`
- Create: `tests/backend/test_route_resolution.py`
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/router_runtime.py`

- [ ] **Step 1: 写失败测试，锁定 `resolved_route` 与 readiness 语义**

```python
from app.domains.crawler_service.extractors.app_readiness import evaluate_app_readiness
from app.domains.crawler_service.extractors.route_resolution import resolve_route_snapshot


def test_resolve_route_prefers_hash_route_over_pathname():
    snapshot = resolve_route_snapshot(
        pathname="/",
        location_hash="#/dashboard",
        router_route=None,
        history_route=None,
    )

    assert snapshot.resolved_route == "/dashboard"
    assert snapshot.route_source == "hash"


def test_app_readiness_requires_route_and_content_to_stabilize():
    readiness = evaluate_app_readiness(
        samples=[
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": False},
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": True},
            {"resolved_route": "/dashboard", "shell_ready": True, "content_ready": True},
        ]
    )

    assert readiness.shell_ready is True
    assert readiness.route_ready is True
    assert readiness.content_ready is True
```

- [ ] **Step 2: 运行测试，确认当前仓库还没有这些能力**

Run: `pytest tests/backend/test_route_resolution.py -v`  
Expected: FAIL，提示模块不存在或 `resolved_route` / readiness 接口未实现。

- [ ] **Step 3: 写最小实现，新增路由解析与 readiness 纯函数**

```python
@dataclass(slots=True)
class RouteSnapshot:
    resolved_route: str
    route_source: str
    pathname: str | None
    hash_route: str | None
    router_route: str | None
    history_route: str | None


def resolve_route_snapshot(*, pathname, location_hash, router_route, history_route) -> RouteSnapshot:
    for source, candidate in (
        ("router", router_route),
        ("hash", extract_hash_route(location_hash)),
        ("history", history_route),
        ("pathname", pathname),
    ):
        normalized = normalize_route(candidate)
        if normalized is not None:
            return RouteSnapshot(
                resolved_route=normalized,
                route_source=source,
                pathname=normalize_route(pathname),
                hash_route=extract_hash_route(location_hash),
                router_route=normalize_route(router_route),
                history_route=normalize_route(history_route),
            )
    return RouteSnapshot(resolved_route="/", route_source="fallback", pathname="/", hash_route=None, router_route=None, history_route=None)
```

- [ ] **Step 4: 在 Playwright 会话中接入路由采样与稳定化调用**

```python
route_snapshot = await self_nonlocal.collect_route_snapshot(crawl_scope="current")
samples.append(
    {
        "resolved_route": route_snapshot["resolved_route"],
        "shell_ready": shell_ready,
        "content_ready": content_ready,
    }
)
readiness = evaluate_app_readiness(samples=samples)
```

- [ ] **Step 5: 运行定向测试**

Run: `pytest tests/backend/test_route_resolution.py tests/backend/test_crawler_service.py -k "route or readiness" -v`  
Expected: PASS，且 crawler 侧新增对 `resolved_route` 的断言。

- [ ] **Step 6: Commit**

```bash
git add backend/src/app/domains/crawler_service/extractors/route_resolution.py \
  backend/src/app/domains/crawler_service/extractors/app_readiness.py \
  backend/src/app/domains/crawler_service/extractors/router_runtime.py \
  backend/src/app/domains/crawler_service/service.py \
  tests/backend/test_route_resolution.py \
  tests/backend/test_crawler_service.py
git commit -m "feat: add crawl route resolution and readiness primitives"
```

### Task 2: NavigationTarget 模型、去重与预算控制

**Files:**
- Create: `backend/src/app/domains/crawler_service/navigation_targets.py`
- Create: `tests/backend/test_navigation_targets.py`
- Modify: `backend/src/app/domains/crawler_service/schemas.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/page_discovery.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/state_probe.py`

- [ ] **Step 1: 写失败测试，锁定导航目标去重与预算**

```python
from app.domains.crawler_service.navigation_targets import NavigationTarget, NavigationTargetRegistry


def test_navigation_target_registry_dedups_by_kind_route_state_and_parent():
    registry = NavigationTargetRegistry(max_targets_per_route=4)
    registry.add(
        NavigationTarget(
            target_kind="tab_switch",
            route_hint="/users",
            state_context={"active_tab": "enabled"},
            parent_target_key="page:/users",
        )
    )
    registry.add(
        NavigationTarget(
            target_kind="tab_switch",
            route_hint="/users",
            state_context={"active_tab": "enabled"},
            parent_target_key="page:/users",
        )
    )

    assert len(registry.targets) == 1
```

- [ ] **Step 2: 运行测试，确认当前尚无统一导航目标模型**

Run: `pytest tests/backend/test_navigation_targets.py -v`  
Expected: FAIL，提示 `navigation_targets.py` 不存在。

- [ ] **Step 3: 实现 `NavigationTarget`、去重键和预算拒绝原因**

```python
@dataclass(slots=True)
class NavigationTarget:
    target_kind: str
    route_hint: str | None
    locator_candidates: list[dict[str, object]] = field(default_factory=list)
    state_context: dict[str, object] = field(default_factory=dict)
    parent_target_key: str | None = None
    discovery_source: str | None = None
    safety_level: str = "readonly"
    materialization_status: str = "discovered"

    def dedupe_key(self) -> str:
        return json.dumps(
            {
                "target_kind": self.target_kind,
                "route_hint": self.route_hint,
                "state_context": self.state_context,
                "parent_target_key": self.parent_target_key,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
```

- [ ] **Step 4: 让页面发现和状态探测先产出目标，再决定是否执行**

```python
targets = registry.extend(dom_menu_targets)
page_targets = [target for target in targets if target.target_kind == "page_route"]
state_targets = [target for target in targets if target.target_kind != "page_route"]
```

- [ ] **Step 5: 运行定向测试**

Run: `pytest tests/backend/test_navigation_targets.py tests/backend/test_page_discovery_extractor.py tests/backend/test_state_probe_extractor.py -v`  
Expected: PASS，且失败原因中开始出现更细粒度的分类值。

- [ ] **Step 6: Commit**

```bash
git add backend/src/app/domains/crawler_service/navigation_targets.py \
  backend/src/app/domains/crawler_service/schemas.py \
  backend/src/app/domains/crawler_service/extractors/page_discovery.py \
  backend/src/app/domains/crawler_service/extractors/state_probe.py \
  tests/backend/test_navigation_targets.py \
  tests/backend/test_page_discovery_extractor.py \
  tests/backend/test_state_probe_extractor.py
git commit -m "feat: add navigation target registry for crawl exploration"
```

### Task 3: 菜单骨架发现与 materialize 流程

**Files:**
- Modify: `backend/src/app/domains/crawler_service/extractors/dom_menu.py`
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Modify: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 写失败测试，覆盖展开后子菜单才出现的时序**

```python
@pytest.mark.anyio
async def test_collect_dom_menu_nodes_materializes_children_after_expand():
    session = HotgoLikeMenuSession()

    nodes = await session.collect_dom_menu_nodes(crawl_scope="full")

    assert {node["label"] for node in nodes} >= {"权限管理", "管理员列表"}
    assert any(node.get("parent_label") == "权限管理" for node in nodes)
```

- [ ] **Step 2: 运行测试，确认现有逻辑只能读当前可见 DOM**

Run: `pytest tests/backend/test_crawler_service.py -k materialize -v`  
Expected: FAIL，子菜单缺失或 `parent_label` 不正确。

- [ ] **Step 3: 在 DOM 菜单提取器中实现“骨架发现 -> 局部展开 -> 容器重扫”**

```python
async def collect_navigation_signals(...):
    skeleton = await self._collect_menu_items(...)
    expand_targets = build_menu_expand_targets(skeleton)
    materialized = await browser_session.materialize_navigation_targets(targets=expand_targets, crawl_scope=crawl_scope)
    merged = merge_menu_skeleton_and_materialized_nodes(skeleton=skeleton, materialized=materialized)
    return merged
```

- [ ] **Step 4: 在浏览器会话中支持 `click + hover + tree expand`**

```python
if target_kind == "menu_expand":
    applied = await self_nonlocal._materialize_menu_target(target)
elif target_kind == "tree_expand":
    applied = await self_nonlocal._materialize_tree_target(target)
```

- [ ] **Step 5: 运行定向测试**

Run: `pytest tests/backend/test_crawler_service.py -k "materialize or menu" -v`  
Expected: PASS，且 HotGo-like 假页面能在展开后产生二级菜单节点。

- [ ] **Step 6: Commit**

```bash
git add backend/src/app/domains/crawler_service/extractors/dom_menu.py \
  backend/src/app/domains/crawler_service/service.py \
  tests/backend/test_crawler_service.py
git commit -m "feat: materialize hidden menu targets during crawl"
```

### Task 4: 页面访问与状态探测重构

**Files:**
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/state_probe.py`
- Modify: `backend/src/app/domains/crawler_service/extractors/page_discovery.py`
- Modify: `tests/backend/test_crawler_service.py`
- Modify: `tests/backend/test_state_probe_extractor.py`

- [ ] **Step 1: 写失败测试，覆盖“先访问页面，再派生状态目标”的主链**

```python
@pytest.mark.anyio
async def test_run_crawl_discovers_page_before_state_probe_targets():
    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.pages_saved >= 2
    assert result.elements_saved >= 2
    assert "route_unresolved" not in result.warning_messages
```

- [ ] **Step 2: 运行测试，确认当前仍存在页面和状态耦合问题**

Run: `pytest tests/backend/test_crawler_service.py tests/backend/test_state_probe_extractor.py -k "state_probe or pages_saved" -v`  
Expected: FAIL，页面数和元素数仍停留在基线值。

- [ ] **Step 3: 重构状态探测为“页面访问后派生目标”**

```python
for page_target in page_targets:
    page_context = await browser_session.visit_page_target(page_target=page_target, crawl_scope=crawl_scope)
    state_targets = build_state_targets_from_page_context(page_context=page_context)
    for state_target in state_targets:
        state_payload = await browser_session.perform_navigation_target(target=state_target, crawl_scope=crawl_scope)
        merge_state_payload(result_store=result_store, payload=state_payload)
```

- [ ] **Step 4: 扩展失败分级和状态上下文合并**

```python
if not payload.applied:
    warnings.append(payload.failure_reason or "action_not_applied")
else:
    merged_context = merge_state_context(page_context.state_context, payload.state_context)
```

- [ ] **Step 5: 运行定向测试**

Run: `pytest tests/backend/test_crawler_service.py tests/backend/test_state_probe_extractor.py tests/backend/test_page_discovery_extractor.py -v`  
Expected: PASS，且 warning 不再只剩 `state_transition_not_applied` 一种。

- [ ] **Step 6: Commit**

```bash
git add backend/src/app/domains/crawler_service/service.py \
  backend/src/app/domains/crawler_service/extractors/state_probe.py \
  backend/src/app/domains/crawler_service/extractors/page_discovery.py \
  tests/backend/test_crawler_service.py \
  tests/backend/test_state_probe_extractor.py \
  tests/backend/test_page_discovery_extractor.py
git commit -m "feat: decouple crawl page visits from state probing"
```

### Task 5: 事实层持久化与 asset compiler 兼容

**Files:**
- Create: `backend/alembic/versions/0014_crawl_navigation_materialization_metadata.py`
- Modify: `backend/src/app/infrastructure/db/models/crawl.py`
- Modify: `backend/src/app/domains/asset_compiler/service.py`
- Modify: `tests/backend/test_initial_schema.py`
- Modify: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: 写失败测试，锁定新增事实字段和编译兼容**

```python
def test_page_elements_table_has_materialization_metadata(inspector):
    columns = {column["name"] for column in inspector.get_columns("page_elements", schema="runlet")}
    assert {"materialized_by", "navigation_diagnostics"} <= columns


@pytest.mark.anyio
async def test_compile_snapshot_keeps_locator_bundle_when_materialized_by_modal(db_session):
    result = await service.compile_snapshot(snapshot_id=snapshot.id)
    assert result.page_check_ids
```

- [ ] **Step 2: 运行测试，确认 schema 和 compiler 尚未支持这些字段**

Run: `pytest tests/backend/test_initial_schema.py tests/backend/test_asset_compiler_service.py -k "materialization or compile_snapshot" -v`  
Expected: FAIL，字段缺失或 compiler 未读取新增上下文。

- [ ] **Step 3: 新增 migration 与模型字段，保持字段最小化**

```python
op.add_column("pages", sa.Column("navigation_diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema="runlet")
op.add_column("page_elements", sa.Column("materialized_by", sa.Text(), nullable=True), schema="runlet")
op.add_column("page_elements", sa.Column("navigation_diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema="runlet")
```

- [ ] **Step 4: 让 asset compiler 忽略式兼容新增字段，而不是承担新职责**

```python
normalized_element = {
    "element_type": element.element_type,
    "state_context": dict(element.state_context or {}),
    "locator_candidates": list(element.locator_candidates or []),
    "materialized_by": element.materialized_by,
}
```

- [ ] **Step 5: 运行定向测试**

Run: `pytest tests/backend/test_initial_schema.py tests/backend/test_asset_compiler_service.py tests/backend/test_locator_bundle_compiler.py -v`  
Expected: PASS，迁移和 compiler 兼容路径通过。

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0014_crawl_navigation_materialization_metadata.py \
  backend/src/app/infrastructure/db/models/crawl.py \
  backend/src/app/domains/asset_compiler/service.py \
  tests/backend/test_initial_schema.py \
  tests/backend/test_asset_compiler_service.py
git commit -m "feat: persist crawl materialization metadata"
```

### Task 6: HotGo 回归样本与全量验证收口

**Files:**
- Modify: `tests/backend/test_crawler_service.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-04-05-crawler-resilience-and-crawl-completeness-design.md`

- [ ] **Step 1: 写失败测试，模拟 `HotGo` 的 hash route + 懒菜单加载时序**

```python
@pytest.mark.anyio
async def test_hotgo_like_session_yields_non_root_pages_and_menu_nodes():
    result = await crawler_service.run_crawl(system_id=seeded_auth_state.system_id, crawl_scope="full")

    assert result.pages_saved >= 3
    assert result.menus_saved >= 2
    assert result.elements_saved >= 2
```

- [ ] **Step 2: 运行测试，确认旧逻辑无法通过回归门槛**

Run: `pytest tests/backend/test_crawler_service.py -k hotgo_like -v`  
Expected: FAIL，页面、菜单或元素数低于门槛。

- [ ] **Step 3: 补齐 fake session / fixture，固定 HotGo-like 时序回归**

```python
class HotgoLikeCrawlerPage(StateProbeAwareFakeCrawlerPage):
    current_hash = "#/dashboard"
    menu_loaded = False

    async def wait_for_timeout(self, timeout: int) -> None:
        await super().wait_for_timeout(timeout)
        if timeout >= 2000:
            self.menu_loaded = True
```

- [ ] **Step 4: 运行全量回归**

Run: `pytest tests/backend/test_route_resolution.py tests/backend/test_navigation_targets.py tests/backend/test_crawler_service.py tests/backend/test_state_probe_extractor.py tests/backend/test_page_discovery_extractor.py tests/backend/test_asset_compiler_service.py tests/backend/test_initial_schema.py tests/backend/test_locator_bundle_compiler.py -v`  
Expected: PASS，全量通过，且 HotGo-like 回归样本不再只产生根页面。

- [ ] **Step 5: 更新文档与变更记录**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-04-05-crawler-resilience-and-crawl-completeness-design.md
```

- [ ] **Step 6: Commit**

```bash
git add tests/backend/test_crawler_service.py CHANGELOG.md
git commit -m "test: add hotgo-like crawl completeness regression"
```

---

## 执行备注

- 严格按 TDD 推进，每个任务都先写失败测试再改实现。
- 不要在 `service.py` 里继续无边界堆脚本常量；能抽到纯函数或独立模块的逻辑优先拆出。
- `asset_compiler` 只做兼容消费，不接管 crawler 的导航与稳定化职责。
- 若 Task 6 全量通过后 `HotGo` 真实联调仍有盲区，再单独补一份“可复用适配层”设计与计划，不在本计划里提前展开。
