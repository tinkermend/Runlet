# 后端采集同步一致性与资产退役设计

**日期：** 2026-04-03  
**作者：** Codex  
**状态：** Draft

---

## 1. 文档定位

本文档定义当前项目后端在“菜单、页面、关键按钮等元素更新或删除后”的采集同步一致性机制，重点解决以下问题：

- `crawler_service` 每次都会产出新的 `crawl_snapshot`，但 `asset_compiler` 当前主要处理新增和漂移打分，缺少显式收敛逻辑
- 页面、菜单或关键元素在新一轮采集中消失后，旧 `page_asset/page_check/intent_alias/published_job` 仍可能继续存活
- 现有 `safe/suspect/stale` 更偏向漂移语义，不足以表达“对象已确认不存在、必须立即阻断”
- 调度、API 受理、worker 执行前校验尚未围绕“资产已删除”形成统一阻断行为

本文档只讨论后端采集同步一致性，不讨论前端、CLI、MCP 或自由 Playwright 脚本生成。设计继续遵守仓库中的核心约束：

- 检查资产是主模型
- Playwright 脚本是派生产物
- 正式执行统一走 `control_plane`
- 认证注入必须由服务端统一处理

---

## 2. 目标、前提与非目标

### 2.1 已确认的治理前提

本设计基于以下已确认决策：

1. 默认采用**保守阻断**策略
2. 一旦确认页面或关键能力已删除，**立即停调度并拒绝执行**
3. 删除判定证据采用：**单次高质量 `full crawl` 缺失即可判定**

这里的“高质量 `full crawl`”必须满足：

- `crawl_scope == full`
- `degraded == false`
- `quality_score` 通过约定阈值
- 页面规模未出现明显异常塌缩

### 2.2 主要目标

本设计的目标如下：

1. 让一次高质量 `full crawl` 成为当前页面资产真相的统一来源
2. 在编译阶段显式收敛旧资产，而不是只打漂移分
3. 将“更新”和“删除”分成两套不同语义
4. 在 `page_asset`、`page_check`、`intent_alias`、`published_job` 四层形成级联退役
5. 保证 control plane、scheduler、worker 对已退役对象统一阻断
6. 为“哪次采集导致了哪个对象退役”提供可追溯审计

### 2.3 非目标

本设计明确不做以下内容：

- 不把低质量或 `degraded` crawl 作为删除真相
- 不让 `runner_service` 自行推断资产是否删除
- 不让调度直接围绕孤立脚本文本继续运行
- 不把所有采集到的 DOM 元素都纳入退役判定，只关注关键元素
- 不把 `pages/menu_nodes/page_elements` 变成长期生命周期真相表

---

## 3. 方案比较与推荐

### 3.1 方案 A：沿用现有漂移打分并加强阈值

做法：

- 继续使用 `safe/suspect/stale`
- 页面或关键元素缺失时，直接映射到 `stale`

优点：

- 改动最小
- 复用现有指纹和状态字段

缺点：

- 无法准确表达“对象已删除”
- 旧 `intent_alias`、调度对象和执行入口仍可能悬挂
- 收敛逻辑不完整

### 3.2 方案 B：以高质量 `full crawl` 为真相，增加显式 reconciliation 与退役

做法：

- `crawler_service` 负责产出事实快照
- `asset_compiler` 负责在编译时同时做新增、更新、退役
- `control_plane` 负责把退役结果级联到 alias、调度和执行面

优点：

- 与“资产是主模型、control plane 统一编排”的边界一致
- 能明确表达“更新”和“删除”
- 能保证调度、解析和执行同步收敛

缺点：

- 需要补 lifecycle 状态、退役原因和审计模型
- 需要在编译链路中加入 reconciliation 步骤

### 3.3 方案 C：建立完整依赖图并按图做级联退役

做法：

- 显式维护 `菜单 -> 页面 -> 关键元素 -> page_check -> published_job` 完整依赖图
- 每次 crawl 后做图级 diff 与级联退役

优点：

- 长期最严谨
- 可解释性最强

缺点：

- 当前阶段实现成本偏高
- 容易超出当前仓库所需复杂度

### 3.4 推荐结论

采用 **方案 B**：

- 高质量 `full crawl` 作为真相输入
- `asset_compiler` 新增 reconciliation 过程
- 退役结果由 `control_plane` 统一向下游传播

该方案足够严格，能满足“删除后立即停调度并拒绝执行”，同时不会把当前系统过度重构成重量级依赖图平台。

---

## 4. 状态模型与退役语义

### 4.1 漂移状态与生命周期状态分离

当前 `safe/suspect/stale` 不足以表达“对象已不存在”。建议将状态拆成两条轴：

1. 漂移状态 `drift_status`

- `safe`
- `suspect`
- `stale`

用于表达：对象仍存在，但结构、导航、定位器或语义发生变化。

2. 生命周期状态 `lifecycle_status`

- `active`
- `retired_missing`
- `retired_replaced`
- `retired_manual`

用于表达：对象是否仍在当前系统真相中存活。

### 4.2 退役语义

本设计最核心的语义是 `retired_missing`：

- 一次高质量 `full crawl` 中，对象在当前真相集合里缺失
- 且该缺失命中页面、关键菜单链或关键元素的删除判定规则
- 则对象立即进入 `retired_missing`

进入 `retired_missing` 后：

- 不再允许命中为执行目标
- 不再允许作为有效 alias 解析结果
- 不再允许继续参与自动调度

### 4.3 页面、检查与页面资产的关系

退役规则按层处理：

1. 页面删除

- 退役对应 `page_asset`
- 连带退役其下全部 `page_check`

2. 关键菜单链删除

- 页面可保留，但依赖该菜单链的 `page_check` 必须退役
- 若页面下所有检查都依赖该导航链，可将页面资产也视为不可执行

3. 关键元素删除

- 页面资产可继续 `active`
- 但依赖该关键元素的 `page_check` 必须退役

这保证系统能做到：

- 页面还活着，但某个检查能力已经删除
- 页面消失时，整页执行能力整体删除

---

## 5. Reconciliation 数据流

### 5.1 总体流程

每次高质量 `full crawl` 完成后，后端按以下顺序处理：

1. `crawler_service`

- 只负责产出 `crawl_snapshots/pages/menu_nodes/page_elements`
- 不负责判定旧资产是否删除

2. `asset_compiler`

- 根据新 snapshot 构造当前真相集合
- 对比当前系统的 active 资产集合
- 产出新增、更新、退役三类结果

3. `control_plane`

- 接收 reconciliation 结果
- 统一级联失效 alias、暂停调度、阻断执行

4. `scheduler` 与 `worker`

- 只消费最终状态
- 不自己猜测对象是否已删除

### 5.2 reconciliation 输入

`asset_compiler` 在 reconciliation 时至少需要三类输入：

1. 当前采集真相集合

- `current_pages`
- `current_menu_paths`
- `current_key_elements`

2. 当前 active 资产集合

- `page_assets`
- `page_checks`
- 当前有效 `intent_aliases`
- 当前 active `published_jobs`

3. 依赖规则

- 页面依赖哪些关键菜单链
- 哪些 `page_check` 依赖哪些关键元素
- 哪些元素属于阻断性关键元素

### 5.3 reconciliation 输出

建议 `compile_snapshot()` 不再只返回创建数量和总体漂移结果，而是返回完整的变更集：

- `assets_created`
- `assets_updated`
- `assets_retired`
- `checks_created`
- `checks_updated`
- `checks_retired`
- `aliases_disabled`
- `published_jobs_paused`
- `retire_reasons`

这样 control plane 收到的是明确同步结果，而不是模糊的“编译成功”。

### 5.4 级联顺序

建议固定按以下顺序处理：

1. 先更新当前仍存在的资产版本
2. 再判定本次缺失对象并执行退役
3. 再停用 alias 与调度对象
4. 最后写入 reconciliation 审计

这样可以减少“先退役再重建”的短暂空窗。

---

## 6. 数据模型设计

### 6.1 `page_assets`

建议新增或重构以下字段：

- `drift_status`
- `lifecycle_status`
- `retired_reason`
- `retired_at`
- `retired_by_snapshot_id`

原 `status` 可迁移为 `drift_status`，避免一个字段同时承担漂移和生命周期语义。

### 6.2 `page_checks`

建议补充：

- `lifecycle_status`
- `retired_reason`
- `retired_at`
- `retired_by_snapshot_id`
- `blocking_dependency_json`

其中 `blocking_dependency_json` 用于声明：

- 该检查依赖的菜单链
- 该检查依赖的关键元素
- 该依赖是导航前提还是断言前提

### 6.3 `intent_aliases`

建议补充：

- `is_active`
- `disabled_reason`
- `disabled_at`
- `disabled_by_snapshot_id`

这样 alias 可以显式失效，而不是继续解析到已退役资产。

### 6.4 调度对象

建议在 `published_jobs` 或对应调度模型补充：

- `pause_reason`
- `paused_by_snapshot_id`
- `paused_by_asset_id`
- `paused_by_page_check_id`

以区分：

- 人工暂停
- 因资产退役而被系统自动暂停

### 6.5 reconciliation 审计表

建议新增 `snapshot_reconciliation_events` 一类的审计表，记录：

- `snapshot_id`
- `system_id`
- `reconciliation_type`
- `quality_gate_passed`
- `created_count`
- `updated_count`
- `retired_count`
- `details_json`

`details_json` 记录：

- 哪个 `page_asset` 被退役
- 原因是页面缺失、菜单链缺失还是关键元素缺失
- 哪些 `page_check` 被连带退役
- 哪些 `published_job` 被自动暂停

---

## 7. 判定规则

### 7.1 页面判定

每个页面必须有稳定身份键，优先采用：

1. `route_path`
2. 若 route 不稳定，再补 `system_code + canonical_page_name`

按稳定键做如下判定：

- 新 snapshot 中存在，同键旧资产也存在：对象仍存在，再比较指纹，决定 `safe/suspect/stale`
- 新 snapshot 中存在，但旧资产不存在：视为新页面
- 新 snapshot 中不存在，但旧资产仍为 `active`：视为页面删除，立即 `retired_missing`

### 7.2 菜单判定

菜单分两类：

1. 普通菜单节点
2. 被某个 `module_plan` 或检查依赖的关键菜单链

规则如下：

- 普通菜单变化：只参与导航漂移，不单独触发退役
- 关键菜单链缺失：退役依赖该导航链的 `page_check`

### 7.3 关键元素判定

关键元素仅来自：

- 已进入 `module_plan` 的交互点
- 已进入 `assertion_schema` 的断言点

规则如下：

- 元素仍在，但文案或 locator 改变：视为更新，进入漂移语义
- 元素在新 snapshot 中不存在：对应 `page_check` 立即 `retired_missing`
- 非关键元素缺失：不触发退役

### 7.4 质量门禁

删除判定必须受质量门禁保护：

- `crawl_scope == full`
- `degraded == false`
- `quality_score` 高于阈值
- 页面规模未出现异常塌缩

若页面数相较上一轮 active 页面数骤降到明显异常区间，则默认记录告警并跳过批量退役。

---

## 8. Control Plane、调度与执行阻断

### 8.1 `control_plane`

解析执行目标时，必须只命中：

- `is_active = true` 的 alias
- `lifecycle_status = active` 的 `page_asset/page_check`

若目标已退役：

- 手动请求直接返回“资产已退役/检查不可执行”
- 自动调度不再投递正常执行任务

本设计下，已退役对象**不允许**回退到 `realtime_probe`。

### 8.2 调度面

一旦 reconciliation 判定相关资产或检查已退役：

- 关联 `published_job` 立即从 `active` 切换为 `paused`
- 写入 `pause_reason = asset_retired_missing`
- 调度注册表同步卸载该任务

### 8.3 worker

worker 在执行前必须再次校验：

- `page_asset.lifecycle_status`
- `page_check.lifecycle_status`
- 若来自发布任务，再校验 `published_job.state`

只要对象已退役或已暂停：

- 当前任务直接标记为 `skipped` 或阻断失败
- 不打开浏览器
- 失败原因写明 `asset_retired_missing`

### 8.4 恢复路径

恢复只能依赖新的高质量 `full crawl` 真相：

- 页面或关键元素重新出现
- 重新编译并重新激活 `page_asset/page_check`
- 重新启用 alias 与调度

不允许仅通过手工修改生命周期字段直接恢复。

---

## 9. 测试与验收标准

### 9.1 测试矩阵

必须覆盖至少五组用例：

1. 页面删除

- 基线存在页面、检查、alias、调度
- 下一次高质量 `full crawl` 中该页面消失
- 断言资产退役、alias 失效、调度暂停、control plane 拒绝、worker 拦截

2. 关键菜单链删除

- 页面仍存在
- 导航该页面所需菜单链缺失
- 断言依赖该链路的 `page_check` 退役

3. 关键按钮删除

- 页面仍存在
- 关键按钮消失
- 断言只有依赖该按钮的 `page_check` 退役，页面资产仍可存活

4. 更新而非删除

- 页面、菜单或关键元素仍可对应上
- 文案或 locator 改变
- 断言只进入漂移语义，不进入退役

5. 低质量采集保护

- `degraded=true` 或质量不达标
- 断言不会触发批量 `retired_missing`

### 9.2 验收标准

完成标准如下：

1. 一次高质量 `full crawl` 缺失页面时，系统可在一次 reconciliation 内完成退役、失效 alias、暂停调度和执行阻断
2. 页面内关键元素删除时，只退役受影响的 `page_check`，不误退役整个页面
3. 低质量或 `degraded` crawl 不会触发删除收敛
4. 任一执行入口都不会命中已退役对象
5. 审计层能追溯“哪次 snapshot 导致哪个对象退役、哪个调度被暂停”

---

## 10. 实施建议

建议按以下顺序实施：

1. 先补生命周期字段和 reconciliation 审计模型
2. 再改造 `asset_compiler`，让其输出完整变更集
3. 再补 `control_plane` 的 alias 过滤、调度暂停与 worker 阻断
4. 最后补端到端回归测试，覆盖页面删除、关键元素删除和低质量保护

该顺序符合仓库既有原则：

- 先完善资产模型和控制面
- 再补运行时收敛
- 不让调度和 worker 绕过后端真相
