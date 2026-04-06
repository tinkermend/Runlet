# Current-State Corpus Switch and History Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将采集事实层收敛为“当前正式语料 + 候选采集批次 + 冷历史归档”模型，确保只有高质量且存在事实层有效变化时才归档旧正式集并原子切换，其他候选一律丢弃，不做无意义 DML。

**Architecture:** 本次实现沿现有 `crawler_service -> crawl_snapshot -> asset_compiler -> page_asset/page_check` 主链演进，而不是引入新的跨域执行入口。`crawler_service` 只负责写入 `draft` 候选批次；`asset_compiler` 新增页面语义指纹比较、无变化丢弃、变更归档和正式切换；历史事实进入独立 `*_hist` 冷数据表，默认业务查询继续只读当前 `active snapshot` 与当前态资产。

**Tech Stack:** FastAPI, SQLModel, Alembic, PostgreSQL, pytest

**执行状态（2026-04-06）**

- Task 1-5 已全部完成，相关提交为 `a718f8f`、`161befd`、`05661ac`、`f46adc7`、`26e45ca`。
- 事实层现已收敛为 `draft -> active/discarded + *_hist` 模型，控制台默认事实读取已收口到当前 `active snapshot`。
- 最终回归验证命令：`uv run --project backend --group dev pytest tests/backend/test_initial_schema.py tests/backend/test_current_state_switch.py tests/backend/test_asset_compiler_service.py tests/backend/test_asset_compile_job.py tests/backend/test_console_assets_api.py -q`
- 最终回归结果：`82 passed in 7.59s`。

---

## 实施约束

- 全流程遵循 `@test-driven-development`：先写失败测试，再写最小实现，再跑绿。
- 保持 `control_plane -> page_asset/page_check -> runner_service` 正式执行主模型不变。
- 删除页面只能在 `quality_score` 达标且 `degraded=false` 时生效。
- 无变化候选不得触发历史归档、不得更新当前正式事实、不得刷新当前态资产。
- 所有变更同步更新 `CHANGELOG.md`，并保持文档与注释使用中文。

## File Structure

**Files to Create:**

- `backend/alembic/versions/0015_current_state_corpus_history.py`
  - 新增 `crawl_snapshots.state`、`activated_at/discarded_at` 等状态字段，以及 `crawl_snapshots_hist/pages_hist/menu_nodes_hist/page_elements_hist` 表。
- `backend/src/app/infrastructure/db/models/crawl_history.py`
  - 定义完整历史归档模型，隔离在线事实表与冷历史表。
- `backend/src/app/domains/asset_compiler/current_state_diff.py`
  - 构建页面语义指纹、比较 `draft`/`active` 页面集合并生成差异结果。
- `backend/src/app/domains/asset_compiler/current_state_switch.py`
  - 执行“无变化丢弃 / 高质量变更归档 + 提升为 active / 低质量丢弃”的事务编排。
- `tests/backend/test_current_state_diff.py`
  - 纯函数测试，锁定页面语义指纹与差异比较规则。
- `tests/backend/test_current_state_switch.py`
  - 服务级测试，锁定无变化、高质量变更、低质量缺页三条主路径。

**Files to Modify:**

- `backend/src/app/infrastructure/db/models/crawl.py`
  - 为 `CrawlSnapshot` 增加状态字段与当前态管理元信息。
- `backend/src/app/infrastructure/db/models/__init__.py`
  - 注册新增历史模型 metadata。
- `backend/src/app/domains/crawler_service/service.py`
  - 新采集默认写入 `draft snapshot`，不再直接把事实当成长期在线历史。
- `backend/src/app/domains/crawler_service/schemas.py`
  - 如有必要，为 `CrawlRunResult` 暴露 `snapshot_state` 或 `switch_pending` 诊断字段。
- `backend/src/app/domains/asset_compiler/service.py`
  - 在 `compile_snapshot()` 中接入当前态比较与切换编排。
- `backend/src/app/domains/asset_compiler/schemas.py`
  - 让编译结果能表达 `no_change/discarded/promoted` 等切换结果。
- `backend/src/app/api/endpoints/console_assets.py`
  - 收口事实查询口径，必要时显式只消费当前 `active` 对应事实。
- `backend/src/app/domains/control_plane/system_admin_service.py`
  - system teardown 时补充 `*_hist` 删除顺序。
- `backend/src/app/domains/control_plane/system_admin_repository.py`
  - 收集和删除历史表 ID，保证 teardown 不留冷历史残留。
- `tests/backend/test_initial_schema.py`
  - 断言新字段、新历史表存在。
- `tests/backend/test_crawler_service.py`
  - 覆盖采集结果默认写入 `draft snapshot`。
- `tests/backend/test_asset_compiler_service.py`
  - 覆盖 compile 对当前态切换的集成行为。
- `tests/backend/test_console_assets_api.py`
  - 覆盖默认控制台查询不混入历史或废弃候选事实。
- `tests/backend/test_system_admin_service.py`
  - 覆盖 teardown 会同时删除 `*_hist` 归档。
- `CHANGELOG.md`
  - 记录本次计划与后续实现约束。

---

### Task 1: 建立当前态/历史态 schema 基线

**Files:**
- Modify: `backend/src/app/infrastructure/db/models/crawl.py`
- Create: `backend/src/app/infrastructure/db/models/crawl_history.py`
- Modify: `backend/src/app/infrastructure/db/models/__init__.py`
- Create: `backend/alembic/versions/0015_current_state_corpus_history.py`
- Test: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: 先写失败测试，声明 snapshot 状态字段和历史表必须存在**

```python
def test_initial_schema_exposes_current_state_snapshot_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {column["name"] for column in inspector.get_columns("crawl_snapshots")}
    assert {"state", "activated_at", "discarded_at"} <= columns


def test_initial_schema_exposes_crawl_history_tables(db_engine):
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())
    assert {
        "crawl_snapshots_hist",
        "pages_hist",
        "menu_nodes_hist",
        "page_elements_hist",
    } <= table_names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_initial_schema.py -k "current_state_snapshot or crawl_history" -v`  
Expected: FAIL，提示 `crawl_snapshots` 缺少状态列或历史表不存在。

- [ ] **Step 3: 最小实现模型与迁移**

```python
class CrawlSnapshot(BaseModel, table=True):
    __tablename__ = "crawl_snapshots"

    ...
    state: str = Field(default="draft", max_length=16)
    activated_at: datetime | None = Field(default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True))
    discarded_at: datetime | None = Field(default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True))
```

```python
class CrawlSnapshotHistory(BaseModel, table=True):
    __tablename__ = "crawl_snapshots_hist"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_active_snapshot_id: UUID = Field(index=True)
    replaced_by_snapshot_id: UUID = Field(index=True)
    archived_at: datetime = Field(default_factory=utcnow)
    archive_reason: str = Field(max_length=64)
```

- [ ] **Step 4: 运行 schema 测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_initial_schema.py -k "current_state_snapshot or crawl_history" -v`  
Expected: PASS，Alembic 可升级到 `head`。

- [ ] **Step 5: Commit**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/infrastructure/db/models/crawl.py \
  backend/src/app/infrastructure/db/models/crawl_history.py \
  backend/src/app/infrastructure/db/models/__init__.py \
  backend/alembic/versions/0015_current_state_corpus_history.py \
  tests/backend/test_initial_schema.py
git commit -m "feat: add current-state crawl history schema"
```

---

### Task 2: 固化页面语义指纹与差异比较纯函数

**Files:**
- Create: `backend/src/app/domains/asset_compiler/current_state_diff.py`
- Create: `tests/backend/test_current_state_diff.py`

- [ ] **Step 1: 先写失败测试，锁定“无变化/新增/删除/关键元素变化”四类差异**

```python
def test_compare_snapshot_truth_returns_no_change_when_semantics_match():
    current = build_snapshot_semantics(
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        elements=[{"kind": "table", "role": "table", "text": "用户列表"}],
    )
    draft = build_snapshot_semantics(
        route_path="/users",
        page_title="用户管理",
        menu_chain=["系统管理", "用户管理"],
        elements=[{"kind": "table", "role": "table", "text": "用户列表"}],
    )
    diff = compare_snapshot_pages(active_pages=[current], draft_pages=[draft])
    assert diff.changed is False
    assert diff.deleted_routes == []


def test_compare_snapshot_truth_detects_deleted_route_only_under_quality_gate():
    diff = compare_snapshot_pages(
        active_pages=[...],
        draft_pages=[],
    )
    assert diff.changed is True
    assert diff.deleted_routes == ["/users"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_current_state_diff.py -v`  
Expected: FAIL，提示 `compare_snapshot_pages` 或语义指纹构造函数不存在。

- [ ] **Step 3: 最小实现页面语义指纹与比较器**

```python
@dataclass(frozen=True)
class PageSemanticFingerprint:
    route_path: str
    page_title: str | None
    menu_chain: tuple[str, ...]
    key_elements: tuple[str, ...]


def compare_snapshot_pages(*, active_pages, draft_pages) -> SnapshotDiffResult:
    active_by_route = {page.route_path: page for page in active_pages}
    draft_by_route = {page.route_path: page for page in draft_pages}
    ...
    return SnapshotDiffResult(changed=bool(changed_routes or deleted_routes or added_routes), ...)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_current_state_diff.py -v`  
Expected: PASS，覆盖无变化、新增、删除、关键元素变化。

- [ ] **Step 5: Commit**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/current_state_diff.py \
  tests/backend/test_current_state_diff.py
git commit -m "feat: add current-state semantic diff"
```

---

### Task 3: 让 `crawler_service` 默认写入 `draft snapshot`

**Files:**
- Modify: `backend/src/app/domains/crawler_service/service.py`
- Modify: `backend/src/app/domains/crawler_service/schemas.py`
- Test: `tests/backend/test_crawler_service.py`

- [ ] **Step 1: 先写失败测试，声明新采集结果默认是 `draft`**

```python
@pytest.mark.anyio
async def test_run_crawl_persists_draft_snapshot_by_default(...):
    result = await crawler_service.run_crawl(system_id=seeded_system.id, crawl_scope="full")
    snapshot = db_session.exec(select(CrawlSnapshot).where(CrawlSnapshot.id == result.snapshot_id)).one()
    assert snapshot.state == "draft"
    assert snapshot.activated_at is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_crawler_service.py -k "draft_snapshot_by_default" -v`  
Expected: FAIL，当前 `CrawlSnapshot` 没有 `state` 字段或默认值不是 `draft`。

- [ ] **Step 3: 最小实现写入语义**

```python
snapshot = CrawlSnapshot(
    system_id=system_id,
    crawl_type=crawl_scope,
    state="draft",
    ...
)
```

```python
return CrawlRunResult(
    ...,
    message=message,
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_crawler_service.py -k "draft_snapshot_by_default" -v`  
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/crawler_service/service.py \
  backend/src/app/domains/crawler_service/schemas.py \
  tests/backend/test_crawler_service.py
git commit -m "feat: persist crawl snapshots as draft candidates"
```

---

### Task 4: 在 `asset_compiler` 中实现无变化丢弃与高质量变更切换

**Files:**
- Create: `backend/src/app/domains/asset_compiler/current_state_switch.py`
- Modify: `backend/src/app/domains/asset_compiler/service.py`
- Modify: `backend/src/app/domains/asset_compiler/schemas.py`
- Create: `tests/backend/test_current_state_switch.py`
- Modify: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: 先写失败测试，锁定三条主路径**

```python
@pytest.mark.anyio
async def test_compile_snapshot_discards_draft_when_semantics_match_active(...):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=draft_snapshot.id)
    refreshed = db_session.get(CrawlSnapshot, draft_snapshot.id)
    assert result.switch_outcome == "discarded_no_change"
    assert refreshed.state == "discarded"


@pytest.mark.anyio
async def test_compile_snapshot_promotes_draft_and_archives_previous_active_on_change(...):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=draft_snapshot.id)
    promoted = db_session.get(CrawlSnapshot, draft_snapshot.id)
    archived = db_session.exec(select(CrawlSnapshotHistory)).all()
    assert result.switch_outcome == "promoted"
    assert promoted.state == "active"
    assert len(archived) == 1


@pytest.mark.anyio
async def test_compile_snapshot_discards_low_quality_draft_without_deleting_missing_active_page(...):
    result = await asset_compiler_service.compile_snapshot(snapshot_id=degraded_draft.id)
    assert result.switch_outcome == "discarded_low_quality"
    assert db_session.get(Page, active_page.id) is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_current_state_switch.py tests/backend/test_asset_compiler_service.py -k "switch_outcome or promotes_draft or discards_draft" -v`  
Expected: FAIL，提示切换编排或结果字段不存在。

- [ ] **Step 3: 最小实现切换编排**

```python
async def apply_current_state_switch(...):
    if not draft_is_high_quality(snapshot):
        snapshot.state = "discarded"
        snapshot.discarded_at = utcnow()
        return "discarded_low_quality"
    if diff.changed is False:
        snapshot.state = "discarded"
        snapshot.discarded_at = utcnow()
        return "discarded_no_change"
    await archive_active_snapshot(...)
    await delete_active_snapshot_facts(...)
    snapshot.state = "active"
    snapshot.activated_at = utcnow()
    return "promoted"
```

- [ ] **Step 4: 在 `compile_snapshot()` 中接入差异比较、切换结果与当前态资产重编译**

```python
switch_outcome = await apply_current_state_switch(...)
if switch_outcome != "promoted":
    return CompileSnapshotResult(..., switch_outcome=switch_outcome)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_current_state_switch.py tests/backend/test_asset_compiler_service.py -k "switch_outcome or promotes_draft or discards_draft" -v`  
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/current_state_switch.py \
  backend/src/app/domains/asset_compiler/service.py \
  backend/src/app/domains/asset_compiler/schemas.py \
  tests/backend/test_current_state_switch.py \
  tests/backend/test_asset_compiler_service.py
git commit -m "feat: switch current-state corpus on semantic change"
```

---

### Task 5: 归档旧正式事实并收口默认查询口径

**Files:**
- Modify: `backend/src/app/api/endpoints/console_assets.py`
- Modify: `tests/backend/test_console_assets_api.py`
- Modify: `backend/src/app/domains/asset_compiler/current_state_switch.py`
- Modify: `tests/backend/test_current_state_switch.py`

- [ ] **Step 1: 先写失败测试，声明控制台默认查询不能混入废弃候选或历史事实**

```python
def test_console_asset_detail_uses_active_page_facts_only(client, ...):
    response = client.get(f"/api/console/assets/{asset_id}", headers=console_headers)
    payload = response.json()
    assert all(item["label"] != "废弃候选菜单" for item in payload["raw_facts"]["menu_nodes"])
```

- [ ] **Step 2: 再写失败测试，声明高质量切换时会归档完整旧正式集**

```python
@pytest.mark.anyio
async def test_promote_draft_archives_active_pages_menus_and_elements(...):
    await asset_compiler_service.compile_snapshot(snapshot_id=draft_snapshot.id)
    assert db_session.exec(select(PageHistory)).count() == 1
    assert db_session.exec(select(MenuNodeHistory)).count() >= 1
    assert db_session.exec(select(PageElementHistory)).count() >= 1
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_console_assets_api.py tests/backend/test_current_state_switch.py -k "active_page_facts_only or archives_active" -v`  
Expected: FAIL。

- [ ] **Step 4: 最小实现归档复制与默认读取收口**

```python
def _copy_pages_to_history(*, active_snapshot_id, replacing_snapshot_id):
    ...

menu_nodes = session.exec(
    select(MenuNode).where(MenuNode.page_id == page.id).where(MenuNode.snapshot_id == page.snapshot_id)
).all()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_console_assets_api.py tests/backend/test_current_state_switch.py -k "active_page_facts_only or archives_active" -v`  
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/api/endpoints/console_assets.py \
  backend/src/app/domains/asset_compiler/current_state_switch.py \
  tests/backend/test_console_assets_api.py \
  tests/backend/test_current_state_switch.py
git commit -m "feat: archive replaced active facts and scope console reads"
```

---

### Task 6: 补齐 system teardown 与全量回归

**Files:**
- Modify: `backend/src/app/domains/control_plane/system_admin_repository.py`
- Modify: `backend/src/app/domains/control_plane/system_admin_service.py`
- Modify: `tests/backend/test_system_admin_service.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 先写失败测试，声明 system teardown 会删除冷历史表残留**

```python
@pytest.mark.anyio
async def test_teardown_system_removes_crawl_history_rows(...):
    await system_admin_service.teardown_system(system_code=onboarded_system.system_code)
    assert db_session.exec(select(CrawlSnapshotHistory)).all() == []
    assert db_session.exec(select(PageHistory)).all() == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_system_admin_service.py -k "crawl_history_rows" -v`  
Expected: FAIL，历史表未纳入 teardown 清理。

- [ ] **Step 3: 最小实现仓储收集与删除顺序**

```python
@dataclass(frozen=True)
class SystemTeardownIds:
    ...
    crawl_snapshot_history_ids: list[UUID]
    page_history_ids: list[UUID]
    menu_node_history_ids: list[UUID]
    page_element_history_ids: list[UUID]
```

```python
for model, ids in [
    ...,
    (PageElementHistory, teardown_ids.page_element_history_ids),
    (MenuNodeHistory, teardown_ids.menu_node_history_ids),
    (PageHistory, teardown_ids.page_history_ids),
    (CrawlSnapshotHistory, teardown_ids.crawl_snapshot_history_ids),
]:
    await self.repository.delete_by_ids(model=model, ids=ids)
```

- [ ] **Step 4: 更新 `CHANGELOG.md`**

```markdown
- 新增当前态语料切换实施计划：采集事实层改为 `draft -> active` 切换并在变更时完整归档旧正式集到 `*_hist`。
```

- [ ] **Step 5: 运行目标回归**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_initial_schema.py tests/backend/test_crawler_service.py tests/backend/test_current_state_diff.py tests/backend/test_current_state_switch.py tests/backend/test_asset_compiler_service.py tests/backend/test_console_assets_api.py tests/backend/test_system_admin_service.py -q`  
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/system_admin_repository.py \
  backend/src/app/domains/control_plane/system_admin_service.py \
  tests/backend/test_system_admin_service.py \
  CHANGELOG.md \
  docs/superpowers/specs/2026-04-06-current-state-corpus-switch-and-history-archive-design.md \
  docs/superpowers/plans/2026-04-06-current-state-corpus-switch-and-history-archive-plan.md
git commit -m "feat: support current-state corpus history teardown"
```
