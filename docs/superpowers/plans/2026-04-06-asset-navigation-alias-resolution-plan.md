# Asset Navigation Alias Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 `page_asset/page_check` 执行主模型的前提下，为资产层新增导航别名能力，支持“叶子菜单唯一自动命中、重名返回候选确认、完整菜单链仅作消歧与解释信息”。

**Architecture:** 本次实现分三层落地。第一层在资产模型中新增 `page_navigation_aliases` 作为导航语义存储；第二层在 `asset_compiler` 中把 `pages/menu_nodes` 编译成页面标题、叶子菜单、完整链路别名；第三层在 `control_plane` 的资产解析与候选查询中统一消费该表，并对重复快照做资产级去重。`crawler_service`、`runner_service` 和脚本渲染链路都不改执行职责。

**Tech Stack:** FastAPI, SQLModel, Alembic, PostgreSQL/SQLite 测试, pytest

---

## 实施约束

- 全流程遵循 `@test-driven-development`：每个任务先写失败测试，再补最小实现。
- 保持候选源只来自 `active page_asset/page_check`，不让最新 crawl 事实直接进入正式页名解析。
- 保持 `intent_aliases` 作为兼容 fallback；新导航别名稳定前不删除旧逻辑。
- 文档语言保持中文；代码与测试说明尽量最小闭环。
- 每个任务结束后更新可验证结果并提交；所有变更同步更新 `CHANGELOG.md`。

## File Structure

**Files to Create:**

- `backend/alembic/versions/0015_page_navigation_aliases.py`
  - 新增 `page_navigation_aliases` 表、索引与回滚逻辑。
- `backend/src/app/domains/asset_compiler/navigation_aliases.py`
  - 负责从 `Page + MenuNode` 派生 `page_title/menu_leaf/menu_chain` 别名集合，并做去重与链路完整性判定。
- `tests/backend/test_navigation_alias_compiler.py`
  - 纯函数级测试，锁定“完整链路 / 仅叶子 / 重复菜单节点 / 缺父链”四类编译行为。

**Files to Modify:**

- `backend/src/app/infrastructure/db/models/assets.py`
  - 新增 `PageNavigationAlias` 模型与 `PageAsset` 关系。
- `backend/src/app/infrastructure/db/models/__init__.py`
  - 确保 metadata 导入链继续覆盖新增模型所在文件。
- `backend/src/app/domains/asset_compiler/service.py`
  - 在编译 `page_asset/page_check` 后写入和停用导航别名。
- `backend/src/app/domains/control_plane/recommendation.py`
  - 扩展候选统计与排序载体，带出 `leaf_text/display_chain/chain_complete`。
- `backend/src/app/domains/control_plane/repository.py`
  - 在 `resolve_page_asset_and_check()` 与 `list_check_candidates()` 中消费导航别名，并做资产级去重与重名判断。
- `backend/src/app/domains/control_plane/schemas.py`
  - 扩展候选返回字段，必要时补充歧义结果承载字段。
- `backend/src/app/domains/control_plane/service.py`
  - 让候选 API 返回扩展字段；若直接解析路径命中多个同名叶子菜单，保持不自动选。
- `tests/backend/test_initial_schema.py`
  - 断言新表和新列存在。
- `tests/backend/conftest.py`
  - 为通用 fixture 补导航别名种子，避免现有候选测试只能依赖 `IntentAlias`。
- `tests/backend/test_asset_compiler_service.py`
  - 覆盖 compile snapshot 后导航别名落库与链路完整性标记。
- `tests/backend/test_control_plane_service.py`
  - 覆盖唯一叶子自动命中、同名叶子不自动命中、缺完整链仍自动命中。
- `tests/backend/test_check_candidates_api.py`
  - 覆盖候选接口返回 `display_chain` 和同资产去重。
- `CHANGELOG.md`
  - 记录本次实现与验证。

---

### Task 1: 建立导航别名 schema 与迁移

**Files:**
- Modify: `backend/src/app/infrastructure/db/models/assets.py`
- Create: `backend/alembic/versions/0015_page_navigation_aliases.py`
- Modify: `tests/backend/test_initial_schema.py`

- [ ] **Step 1: 先写失败测试，声明新表必须存在**

```python
def test_initial_schema_exposes_core_tables(db_engine):
    inspector = inspect(db_engine)
    table_names = set(inspector.get_table_names())
    assert "page_navigation_aliases" in table_names


def test_initial_schema_exposes_navigation_alias_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {column["name"] for column in inspector.get_columns("page_navigation_aliases")}
    assert {
        "system_id",
        "page_asset_id",
        "alias_type",
        "alias_text",
        "leaf_text",
        "display_chain",
        "chain_complete",
        "source",
        "is_active",
    } <= columns
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_initial_schema.py -k "navigation_alias or core_tables" -v`
Expected: FAIL，提示 `page_navigation_aliases` 表或列不存在。

- [ ] **Step 3: 最小实现模型与 Alembic 迁移**

```python
class PageNavigationAlias(BaseModel, table=True):
    __tablename__ = "page_navigation_aliases"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_id: UUID = Field(foreign_key="systems.id", index=True)
    page_asset_id: UUID = Field(foreign_key="page_assets.id", index=True)
    alias_type: str = Field(max_length=32, index=True)
    alias_text: str = Field(max_length=512, index=True)
    leaf_text: str | None = Field(default=None, max_length=255)
    display_chain: str | None = Field(default=None, max_length=1024)
    chain_complete: bool = Field(default=False)
    source: str = Field(max_length=64)
    is_active: bool = Field(default=True, sa_column=sa.Column(sa.Boolean(), nullable=False, server_default=sa.true()))
    disabled_reason: str | None = Field(default=None, max_length=64)
    disabled_at: datetime | None = Field(default=None, sa_column=sa.Column(sa.DateTime(timezone=True), nullable=True))
    disabled_by_snapshot_id: UUID | None = Field(default=None, foreign_key="crawl_snapshots.id")
```

```python
op.create_table(
    "page_navigation_aliases",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
    sa.Column("system_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("systems.id"), nullable=False),
    sa.Column("page_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("page_assets.id"), nullable=False),
    sa.Column("alias_type", sa.String(length=32), nullable=False),
    sa.Column("alias_text", sa.String(length=512), nullable=False),
    ...
)
```

- [ ] **Step 4: 运行 schema 测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_initial_schema.py -k "navigation_alias or core_tables" -v`
Expected: PASS，且 Alembic 能升级到 `head`。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/infrastructure/db/models/assets.py backend/alembic/versions/0015_page_navigation_aliases.py tests/backend/test_initial_schema.py
git commit -m "feat: add page navigation alias schema"
```

---

### Task 2: 编写导航别名编译纯函数

**Files:**
- Create: `backend/src/app/domains/asset_compiler/navigation_aliases.py`
- Create: `tests/backend/test_navigation_alias_compiler.py`

- [ ] **Step 1: 先写失败测试，锁定链路编译规则**

```python
def test_build_navigation_aliases_emits_title_leaf_and_chain_when_chain_complete():
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menus=[
            MenuNode(label="数据库", depth=0, sort_order=1),
            MenuNode(label="配置管理", depth=1, sort_order=1),
            MenuNode(label="指标管理", depth=2, sort_order=1),
        ],
    )
    assert {item.alias_type for item in aliases} == {"page_title", "menu_leaf", "menu_chain"}
    assert any(item.display_chain == "数据库 -> 配置管理 -> 指标管理" for item in aliases)


def test_build_navigation_aliases_keeps_leaf_when_parent_chain_missing():
    aliases = build_navigation_aliases(
        page_title="指标管理",
        route_path="/front/database/configManage/indicesManage",
        menus=[MenuNode(label="指标管理", depth=0, sort_order=11)],
    )
    assert any(item.alias_type == "menu_leaf" and item.chain_complete is False for item in aliases)
    assert not any(item.alias_type == "menu_chain" for item in aliases)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_navigation_alias_compiler.py -v`
Expected: FAIL，提示 `build_navigation_aliases` 尚不存在。

- [ ] **Step 3: 最小实现导航别名编译器**

```python
@dataclass(frozen=True)
class NavigationAliasDraft:
    alias_type: str
    alias_text: str
    leaf_text: str | None
    display_chain: str | None
    chain_complete: bool


def build_navigation_aliases(*, page_title: str | None, route_path: str, menus: list[MenuNode]) -> list[NavigationAliasDraft]:
    normalized_chain = _derive_menu_chain(menus)
    drafts = []
    if page_title:
        drafts.append(NavigationAliasDraft("page_title", page_title, normalized_chain[-1] if normalized_chain else page_title, _format_chain(normalized_chain), bool(normalized_chain)))
    if normalized_chain:
        drafts.append(NavigationAliasDraft("menu_leaf", normalized_chain[-1], normalized_chain[-1], _format_chain(normalized_chain), len(normalized_chain) > 1))
    if len(normalized_chain) > 1:
        drafts.append(NavigationAliasDraft("menu_chain", _format_chain(normalized_chain), normalized_chain[-1], _format_chain(normalized_chain), True))
    return _dedupe_drafts(drafts)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_navigation_alias_compiler.py -v`
Expected: PASS，覆盖完整链、仅叶子、重复节点去重。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/navigation_aliases.py tests/backend/test_navigation_alias_compiler.py
git commit -m "feat: derive navigation alias drafts from menu facts"
```

---

### Task 3: 将导航别名写入 `asset_compiler`

**Files:**
- Modify: `backend/src/app/domains/asset_compiler/service.py`
- Modify: `backend/src/app/infrastructure/db/models/assets.py`
- Modify: `tests/backend/test_asset_compiler_service.py`

- [ ] **Step 1: 先写失败测试，声明 compile snapshot 必须落库导航别名**

```python
@pytest.mark.anyio
async def test_compile_snapshot_persists_navigation_aliases(db_session, seeded_snapshot, seeded_system):
    result = await AssetCompilerService(session=db_session).compile_snapshot(snapshot_id=seeded_snapshot.id)
    aliases = db_session.exec(
        select(PageNavigationAlias).where(PageNavigationAlias.page_asset_id == result.page_asset_ids[0])
    ).all()
    assert any(row.alias_type == "menu_leaf" for row in aliases)
    assert any(row.alias_type == "menu_chain" for row in aliases)


@pytest.mark.anyio
async def test_compile_snapshot_marks_leaf_only_alias_incomplete_when_chain_missing(...):
    aliases = ...
    assert any(row.alias_type == "menu_leaf" and row.chain_complete is False for row in aliases)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_asset_compiler_service.py -k "navigation_alias" -v`
Expected: FAIL，提示 `PageNavigationAlias` 未写入或 `chain_complete` 结果不符。

- [ ] **Step 3: 最小实现编译写入与停用逻辑**

```python
drafts = build_navigation_aliases(
    page_title=page.page_title,
    route_path=page.route_path,
    menus=menus_by_page.get(page.id, []),
)
await self._replace_navigation_aliases(
    system_id=system.id,
    page_asset_id=page_asset.id,
    snapshot_id=snapshot.id,
    drafts=drafts,
)
```

```python
async def _replace_navigation_aliases(...):
    existing = await self._exec_all(
        select(PageNavigationAlias).where(PageNavigationAlias.page_asset_id == page_asset_id)
    )
    for row in existing:
        row.is_active = False
        row.disabled_reason = "recompiled"
        row.disabled_at = _utcnow()
        row.disabled_by_snapshot_id = snapshot_id
    for draft in drafts:
        self.session.add(PageNavigationAlias(...))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_navigation_alias_compiler.py tests/backend/test_asset_compiler_service.py -k "navigation_alias" -v`
Expected: PASS，且重复编译不会产生同资产重复别名。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/asset_compiler/service.py backend/src/app/infrastructure/db/models/assets.py tests/backend/test_asset_compiler_service.py
git commit -m "feat: persist navigation aliases during asset compile"
```

---

### Task 4: 改造直接解析路径，支持唯一叶子自动命中

**Files:**
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `tests/backend/test_control_plane_service.py`
- Modify: `tests/backend/conftest.py`

- [ ] **Step 1: 先写失败测试，锁定直接解析规则**

```python
@pytest.mark.anyio
async def test_accept_check_request_resolves_unique_leaf_alias(control_plane_service, db_session):
    _seed_navigation_alias(db_session, alias_type="menu_leaf", alias_text="指标管理", asset_key="erp.users")
    accepted = await control_plane_service.accept_check_request(
        system_hint="ERP",
        page_hint="指标管理",
        check_goal="table_render",
    )
    assert accepted.page_check_id is not None


@pytest.mark.anyio
async def test_accept_check_request_does_not_auto_resolve_ambiguous_leaf_alias(...):
    _seed_navigation_alias(... asset_key="erp.a", alias_text="指标管理")
    _seed_navigation_alias(... asset_key="erp.b", alias_text="指标管理")
    accepted = await control_plane_service.accept_check_request(...)
    assert accepted.page_check_id is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_control_plane_service.py -k "unique_leaf_alias or ambiguous_leaf_alias" -v`
Expected: FAIL，当前仓储仍只依赖 `IntentAlias/page_title/route`。

- [ ] **Step 3: 最小实现资产解析逻辑**

```python
navigation_matches = await self._exec_all(
    select(PageAsset, PageCheck, PageNavigationAlias)
    .join(PageCheck, PageCheck.page_asset_id == PageAsset.id)
    .join(PageNavigationAlias, PageNavigationAlias.page_asset_id == PageAsset.id)
    .where(PageNavigationAlias.is_active.is_(True))
    .where(func.lower(PageNavigationAlias.alias_text) == normalized_page_hint)
    .where(PageAsset.lifecycle_status == AssetLifecycleStatus.ACTIVE)
    .where(PageCheck.lifecycle_status == AssetLifecycleStatus.ACTIVE)
)
deduped = _dedupe_by_page_check(navigation_matches)
if len(deduped) == 1:
    return CheckResolution(system=system, page_asset=deduped[0].page_asset, page_check=deduped[0].page_check, miss_reason=None)
if len(deduped) > 1:
    return CheckResolution(system=system, page_asset=None, page_check=None, miss_reason="ambiguous_page_alias")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_control_plane_service.py -k "unique_leaf_alias or ambiguous_leaf_alias" -v`
Expected: PASS，唯一叶子自动命中，重名时保持未解析。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/service.py tests/backend/test_control_plane_service.py tests/backend/conftest.py
git commit -m "feat: resolve unique page leaf aliases in control plane"
```

---

### Task 5: 改造候选 API，返回链路解释并对重复资产去重

**Files:**
- Modify: `backend/src/app/domains/control_plane/recommendation.py`
- Modify: `backend/src/app/domains/control_plane/repository.py`
- Modify: `backend/src/app/domains/control_plane/schemas.py`
- Modify: `backend/src/app/domains/control_plane/service.py`
- Modify: `tests/backend/test_check_candidates_api.py`
- Modify: `tests/backend/test_control_plane_service.py`

- [ ] **Step 1: 先写失败测试，声明候选结果必须带链路信息并去重**

```python
def test_post_check_request_candidates_returns_display_chain(client, seeded_page_asset):
    response = client.post(
        "/api/v1/check-requests:candidates",
        json={"system_hint": "ERP", "page_hint": "指标管理", "intent": "是否有数据"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["leaf_text"] == "指标管理"
    assert body["candidates"][0]["display_chain"] == "数据库 -> 配置管理 -> 指标管理"


def test_list_check_candidates_dedupes_same_asset_multiple_alias_rows(...):
    candidates = await repository.list_check_candidates(system_hint="ERP", page_hint="指标管理")
    assert len([item for item in candidates if item.asset_key == "erp.users"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_check_candidates_api.py tests/backend/test_control_plane_service.py -k "display_chain or dedupes_same_asset" -v`
Expected: FAIL，当前响应不包含 `leaf_text/display_chain/chain_complete`，重复 alias 行可能重复出现在候选里。

- [ ] **Step 3: 最小实现候选查询与响应扩展**

```python
@dataclass(frozen=True)
class CheckCandidateStats:
    ...
    leaf_text: str | None
    display_chain: str | None
    chain_complete: bool
```

```python
class CheckCandidateItem(BaseModel):
    ...
    leaf_text: str | None = None
    display_chain: str | None = None
    chain_complete: bool = False
```

```python
statement = (
    select(
        PageCheck.id,
        PageCheck.page_asset_id,
        PageAsset.asset_key,
        PageCheck.check_code,
        PageCheck.goal,
        func.max(PageNavigationAlias.leaf_text).label("leaf_text"),
        func.max(PageNavigationAlias.display_chain).label("display_chain"),
        func.max(sa.case((PageNavigationAlias.chain_complete.is_(True), 1), else_=0)).label("chain_complete"),
        ...
    )
    .outerjoin(PageNavigationAlias, ...)
    .group_by(PageCheck.id, PageCheck.page_asset_id, PageAsset.asset_key, PageAsset.asset_version, ...)
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && pytest tests/backend/test_check_candidates_api.py tests/backend/test_control_plane_service.py -k "candidate" -v`
Expected: PASS，候选结果带链路解释字段，且同资产不会因重复 alias 行被重复返回。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add backend/src/app/domains/control_plane/recommendation.py backend/src/app/domains/control_plane/repository.py backend/src/app/domains/control_plane/schemas.py backend/src/app/domains/control_plane/service.py tests/backend/test_check_candidates_api.py tests/backend/test_control_plane_service.py
git commit -m "feat: expose navigation alias candidate metadata"
```

---

### Task 6: 完成回归验证与文档收口

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 先写失败校验，确认 changelog 尚未记录本次实现**

```bash
cd /Users/wangpei/src/singe/Runlet
rg -n "navigation alias|导航别名|叶子菜单唯一自动命中" CHANGELOG.md
```

- [ ] **Step 2: 运行校验确认失败或内容不完整**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "navigation alias|导航别名|叶子菜单唯一自动命中" CHANGELOG.md`
Expected: 非零退出码或未覆盖本次实现要点。

- [ ] **Step 3: 更新变更记录并执行回归套件**

```md
### Added
- 新增 `page_navigation_aliases` 资产层导航语义表与编译/候选查询能力，支持叶子菜单唯一自动命中、重名返回候选确认，并为候选接口补充 `leaf_text/display_chain/chain_complete` 字段。
```

Run:

```bash
cd /Users/wangpei/src/singe/Runlet
pytest tests/backend/test_initial_schema.py -k "navigation_alias or core_tables" -v
pytest tests/backend/test_navigation_alias_compiler.py -v
pytest tests/backend/test_asset_compiler_service.py -k "navigation_alias" -v
pytest tests/backend/test_control_plane_service.py -k "leaf_alias or candidate" -v
pytest tests/backend/test_check_candidates_api.py -v
```

Expected: 全部 PASS。

- [ ] **Step 4: 运行回归确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && git diff --stat`
Expected: 仅包含计划中的模型、迁移、编译器、仓储、schema、测试与 changelog 变更。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add CHANGELOG.md
git commit -m "docs: record navigation alias resolution rollout"
```

---

## 实施后验收标准

- `page_navigation_aliases` 表存在，迁移可在 SQLite 与 PostgreSQL 测试环境升级。
- `asset_compiler` 能为页面生成 `page_title/menu_leaf/menu_chain` 导航别名，并正确标记 `chain_complete`。
- 直接解析路径在唯一叶子菜单场景下可自动命中对应 `page_check`。
- 候选接口在同名叶子菜单场景下能返回带完整链路解释的多个候选。
- 候选结果不会因重复 crawl snapshot/menu 节点放大为重复资产候选。
- 缺完整链但叶子唯一的资产仍可自动命中。

## 风险提醒

- 当前 `dpm` 库中存在重复 `Page/MenuNode` 事实，实施时不要依赖“一个 route 只会出现一条事实记录”。
- 若仓储查询在 SQL 层去重设计不当，PostgreSQL 很容易再次出现 `GROUP BY / ORDER BY` 兼容问题；每次改查询都要用现有 PG SQL 形态测试锁住。
- 兼容期内 `intent_aliases` 与 `page_navigation_aliases` 可能同时命中同一资产，必须在仓储层按 `page_check_id` 或 `asset_key + check_code` 去重。
