# 资产层导航别名解析设计

**日期：** 2026-04-06  
**作者：** Codex  
**状态：** Draft

---

## 1. 文档定位

本文档定义 Runlet 在资产主模型前提下的“页面导航别名解析”设计，用于解决企业 Web 系统存在多级菜单嵌套时，仅凭页面标题或 route 难以稳定命中目标页面的问题。

本文档只讨论以下范围：

- 如何在 `active page_asset/page_check` 范围内补充可检索的导航语义
- 如何支持“叶子菜单唯一自动命中、重名返回候选确认”
- 如何让完整菜单链成为消歧信息与解释信息

本文档不改变以下边界：

- 检查资产仍是主模型
- 正式执行仍统一走 `control_plane`
- Playwright 脚本仍只是派生产物
- `crawler_service` 不直接参与正式执行解析

---

## 2. 背景与问题

### 2.1 当前问题

当前用户会提出如下请求：

- `看一下 dpm 这个系统 指标管理 页面是否有数据`

这类表达通常只给出系统名与叶子菜单名，而企业后台常见导航实际是多级链路，例如：

- `数据库 -> 配置管理 -> 指标管理`

如果资产命中层只依赖页面标题、route 或单字符串别名，就会出现两个问题：

1. 叶子菜单本身缺少“它属于哪条菜单链”的上下文，重名时无法稳定消歧。
2. 即使事实层采到了菜单树，若没有把导航语义编译成资产层的一等检索信息，`control_plane` 仍无法稳定消费。

### 2.2 当前系统的真实状态

当前仓库并非完全没有菜单层级信息：

- `menu_nodes` 已包含 `parent_id / depth / page_id`
- `asset_compiler` 已在 `module_plan` 中生成 `nav.menu_chain`
- `runner_service` 已能消费 `nav.menu_chain`

但当前自然语言页名解析仍主要依赖：

- `intent_aliases.page_alias`
- `pages.page_title`
- `pages.route_path`

这带来两个结构性缺口：

1. `intent_aliases` 更像单字符串别名表，无法稳定表达“叶子菜单 / 全链路 / 展示链路 / 链路完整性”。
2. 现有候选查询没有把导航语义作为一等检索键，因此像“指标管理”这类叶子菜单词，命中能力依赖偶然的页面标题一致，而不是正式规则。

### 2.3 当前数据质量风险

以 `dpm` 为例，当前数据库中同一路由存在重复页面与菜单记录，且部分菜单节点缺少父链，导致事实层并不总能稳定还原完整链路。说明本次设计不能要求“必须有完整菜单链才能解析”，而必须满足：

- 缺完整链但叶子菜单唯一时，仍允许自动命中

---

## 3. 设计目标与非目标

### 3.1 目标

1. 保持候选源只来自 `active page_asset/page_check`。
2. 让叶子菜单名成为资产层正式可检索语义。
3. 在叶子菜单唯一时自动命中。
4. 在叶子菜单重名时返回多个候选给上层确认。
5. 让完整菜单链成为标准消歧与解释信息。
6. 保持无完整链资产在“叶子唯一”前提下仍可被自动命中。

### 3.2 非目标

1. 不让 `crawler_service` 直接参与正式执行解析。
2. 不把 `menu_nodes` 直接提升为执行主模型。
3. 不要求用户必须输入完整菜单链。
4. 不改变 `page_check + module_plan` 的正式执行真相。
5. 不在本次设计中重构 `runner_service` 或脚本渲染链路。

---

## 4. 方案比较与推荐

### 4.1 方案 A：继续扩展 `intent_aliases`

做法：

- 继续向 `intent_aliases.page_alias` 写入更多字符串，例如叶子菜单名或链路字符串

优点：

- 改动最小
- 短期可快速接入候选查询

缺点：

- 仍然无法清晰区分页面标题别名与导航别名
- 难以表达链路展示信息、叶子文本、链路完整性
- 后续禁用错误导航语义时治理成本高

### 4.2 方案 B：新增资产层导航别名表（推荐）

做法：

- 在资产层新增专门的导航别名模型，例如 `page_navigation_aliases`
- 每条记录附着到一个 `page_asset`
- 分类型存储页面标题、叶子菜单、完整链路等语义

优点：

- 语义清晰，便于治理
- 能直接支持候选展示与重名消歧
- 保持“导航语义属于资产层，而不是事实层直接参与执行”

缺点：

- 需要新增模型、编译步骤与查询逻辑

### 4.3 方案 C：将导航树提升为独立执行资产

做法：

- 单独建立导航资产子域，先解析导航资产再映射到 `page_asset/page_check`

优点：

- 长期治理能力最强

缺点：

- 超出当前问题边界
- 会显著扩大本次改造范围

### 4.4 推荐结论

采用方案 B：

- 候选源仍只来自 `active page_asset/page_check`
- 导航语义正式进入资产层
- 完整菜单链只用于消歧与解释，不成为执行主模型

---

## 5. 总体设计

### 5.1 主规则

本次设计固定以下解析规则：

1. 候选只来自 `active page_asset/page_check`
2. 用户输入叶子菜单名时，先按资产层导航别名召回
3. 若只命中一个候选，则自动命中
4. 若命中多个同名叶子菜单，则返回候选列表，由上层确认
5. 若资产缺少完整菜单链，但叶子菜单唯一，仍允许自动命中
6. 完整菜单链只承担“解释信息 + 消歧信息”的职责

### 5.2 命中主轴

当前主轴大致是：

`system_hint + page_title/route_hint -> page_asset/page_check`

改造后扩展为：

`system_hint + (page_title | menu_leaf | menu_chain) -> active page_asset/page_check`

正式执行主轴保持不变：

`page_asset -> page_check -> module_plan -> runner_service`

---

## 6. 数据模型设计

### 6.1 新增模型：`page_navigation_aliases`

建议新增 `page_navigation_aliases`，作为附着在 `page_asset` 上的资产层导航解析表。

建议最少字段如下：

- `id`
- `system_id`
- `page_asset_id`
- `alias_type`
  - `page_title`
  - `menu_leaf`
  - `menu_chain`
- `alias_text`
- `leaf_text`
- `display_chain`
- `chain_complete`
- `source`
- `is_active`
- `disabled_reason`
- `disabled_at`
- `disabled_by_snapshot_id`

### 6.2 字段语义

- `alias_text`
  - 实际参与查询匹配的文本
- `leaf_text`
  - 标准叶子菜单文本，用于重名判断与候选展示
- `display_chain`
  - 展示给上层的完整链路文本，例如 `数据库 -> 配置管理 -> 指标管理`
- `chain_complete`
  - 标记当前资产是否具备可信的完整链路

### 6.3 与现有模型关系

- `page_asset` 继续作为页面资产主记录
- `page_check` 继续作为正式执行对象
- `intent_aliases` 暂时保留，作为兼容层
- `page_navigation_aliases` 只承担“资产层页面解析”职责，不承担执行职责

---

## 7. 资产编译策略

### 7.1 编译输入

`asset_compiler` 继续从当前事实层读取：

- `pages`
- `menu_nodes`
- `intent_aliases` 上下文

但导航别名编译结果必须写回资产层，而不是让事实层直接参与候选查询。

### 7.2 编译规则

对每个 `page_asset`：

1. 总是生成一条 `page_title` 类型别名
2. 若可识别叶子菜单，则生成一条 `menu_leaf`
3. 若可还原完整链路，则生成一条 `menu_chain`

对应规则如下：

- 有完整链路：
  - 生成 `page_title`
  - 生成 `menu_leaf`
  - 生成 `menu_chain`
  - `chain_complete = true`
- 无完整链路但能识别叶子菜单：
  - 生成 `page_title`
  - 生成 `menu_leaf`
  - 不生成 `menu_chain`
  - `chain_complete = false`
- 连叶子菜单都无法稳定识别：
  - 至少保留 `page_title`

### 7.3 去重与稳定性要求

编译时必须避免以下问题：

- 同一路由重复快照导致同一资产产生重复导航别名
- 重复 `menu_nodes` 导致同一 `display_chain` 被重复写入
- 事实层链路不完整时误生成伪完整链路

建议去重维度至少包含：

- `page_asset_id`
- `alias_type`
- `alias_text`

---

## 8. 候选查询与消歧流程

### 8.1 两阶段模型

候选解析拆为两阶段：

1. 资产候选召回
2. 消歧决策

### 8.2 资产候选召回

输入：

- `system_hint`
- `page_hint`

召回来源：

- `active page_asset/page_check`
- `page_navigation_aliases`
- 兼容期内可附加 `intent_aliases`

召回键按语义包括：

- `page_title`
- `menu_leaf`
- `menu_chain`

默认用户主场景优先消费：

- `menu_leaf`
- `page_title`

### 8.3 消歧规则

1. 若只命中 1 个候选，直接自动命中
2. 若命中多个候选，但只有 1 个候选满足标准叶子菜单精确命中，且其他仅为宽松匹配，可直接命中该候选
3. 若命中多个同名叶子菜单，不自动选择，直接返回候选列表给上层确认
4. 若没有候选，保持当前 miss 路径

### 8.4 候选返回结构

重名场景返回给上层的候选最少需要包含：

- `page_asset_id`
- `page_check_id`
- `asset_key`
- `check_code`
- `goal`
- `leaf_text`
- `display_chain`
- `chain_complete`

其中：

- `leaf_text` 用于告诉上层“重名的是哪个叶子菜单”
- `display_chain` 用于让用户理解“它属于哪条菜单链”
- `chain_complete` 用于提示当前链路是否可信完整

---

## 9. 兼容策略

### 9.1 兼容期安排

为避免影响当前已依赖 `intent_aliases` 的链路，本次设计采用渐进兼容：

1. 新增 `page_navigation_aliases`
2. `asset_compiler` 开始写入导航别名
3. 候选查询优先消费 `page_navigation_aliases`
4. `intent_aliases` 暂时保留为兼容 fallback

### 9.2 兼容原则

- 旧页面标题命中能力不能回退
- 旧 route hint 命中能力可保留，但不再作为主要语义入口
- 新导航别名稳定后，再决定是否逐步收缩 `intent_aliases` 的导航职责

---

## 10. 错误处理与业务结果

本次设计需要明确区分两类结果：

### 10.1 `no_candidate`

含义：

- 当前 `active page_asset/page_check` 中没有任何页面可与 `page_hint` 匹配

处理：

- 保持当前 miss 语义
- 不伪造候选

### 10.2 `ambiguous_candidate`

含义：

- 命中了多个同名叶子菜单候选

处理：

- 这是正常业务结果，不应作为系统异常
- 返回候选列表给上层确认

---

## 11. 测试范围

最少需要补充以下测试：

1. 叶子菜单唯一命中时自动通过
2. 同名叶子菜单时返回多个候选，并携带 `display_chain`
3. 缺完整链但叶子唯一时，仍自动命中
4. 只有 `page_title` 没有导航别名时，旧命中链仍可工作
5. 非 `active` 的 `page_asset/page_check` 不进入候选
6. 同一路由重复快照不会返回重复候选
7. 事实层链路缺失时不会误生成伪完整链路

---

## 12. 风险与后续工作

### 12.1 已知风险

当前事实层仍存在以下质量问题：

- 同一路由出现重复 `pages/menu_nodes`
- 部分 `menu_nodes` 丢失父子链

如果不先在资产编译与候选查询阶段做去重，导航别名能力可能把脏数据放大为脏候选。

### 12.2 后续工作

本设计落地后，下一步实施计划应至少覆盖：

1. 新模型与迁移
2. `asset_compiler` 导航别名编译
3. `control_plane` 候选查询改造
4. 候选返回结构扩展
5. 回归测试与 dpm 实例验证

---

## 13. 结论

本次设计的核心判断是：

- 导航层级信息应被编译为资产层可治理语义
- 但它不应直接取代 `page_asset/page_check` 成为新的执行主模型

因此，Runlet 应在资产层新增专门的导航别名能力，使系统具备以下稳定规则：

- 叶子菜单唯一时自动命中
- 叶子菜单重名时返回候选确认
- 完整菜单链作为消歧与解释信息
- 缺完整链时不阻断唯一叶子菜单的自动命中

这条路径既能解决当前“指标管理”类页面解析问题，也不破坏现有“资产优先、控制面统一编排、执行链受控”的总体架构。
