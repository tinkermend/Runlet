# 示教驱动的企业级功能测试编译链设计

**日期：** 2026-04-06  
**作者：** Codex  
**状态：** Draft

---

## 1. 背景与问题

当前 `Runlet` 已具备一条较清晰的正式执行主链：

- `AI Chat / Skills -> control_plane -> asset_compiler -> runner_service`
- 运行时默认从 `intent_aliases -> page_assets -> page_checks` 命中
- 正式执行统一由服务端注入认证
- `script_render` 只是派生产物，不是系统真相

这条链已经适合处理：

- 页面可达性检查
- 菜单/状态入口检查
- 数据存在性与参数化断言
- 调度型轻量巡检

但对企业系统更高价值的“功能上线后的跨页面业务功能测试”仍存在明显缺口：

- 只依赖页面资产与只读断言，不足以覆盖真实业务功能流
- 传统录制 + 重放方案稳定性差，页面轻微变化后经常整流重录
- 纯 AI 动态推理适配性高，但执行成本高、正确率波动大、正式执行难治理
- 拖拉拽工作流虽然可视化，但长期容易退化为低代码测试编排器，且与当前“资产优先”主线不一致

本设计要解决的问题是：

**如何在不破坏当前资产优先架构的前提下，引入一条适合企业级功能测试的“示教驱动编译链”，同时覆盖轻量巡检与复杂功能测试两类场景。**

---

## 2. 设计目标与非目标

### 2.1 目标

1. 保持当前轻量巡检主链不变，继续以 `page_check + module_plan` 为正式对象。
2. 新增一条“示教驱动的功能测试编译链”，支持复杂交互与跨页面业务流。
3. 录制内容不直接作为系统真相，而是作为编译输入，自动生成可复用的正式任务对象。
4. 支持受控写操作功能测试，但要求绑定测试身份、环境和风险分级。
5. 尽量实现“自动生成草案，用户只做一次总确认”。
6. 保持与当前五个核心子域兼容，不引入第二套割裂的平台。

### 2.2 非目标

1. 不把系统演进为通用浏览器 Agent。
2. 不让自由 Playwright 脚本成为正式执行真相。
3. 不在第一阶段支持跨系统业务流。
4. 不在第一阶段支持条件分支、循环、并行等完整工作流语义。
5. 不在第一阶段承诺全自动自修复。
6. 不允许本地浏览器登录态直接成为正式执行主链。

### 2.3 安全边界

- 正式执行仍由平台统一编排。
- 正式认证仍由服务端统一注入。
- 可写场景必须绑定测试身份，不允许默认复用普通用户身份。
- 写操作需显式风险分级，不允许无边界自动执行。
- 外部业务系统本身的权限与限制是第一层边界，`Runlet` 提供第二层平台边界，而非替代全部门控。

---

## 3. 总体产品拆分

本设计确认 `Runlet` 面向 To B 自动化仿真与测试时，应拆成两条产品路径，但共用同一平台内核。

### 3.1 路径一：轻量巡检路径

主链保持不变：

- AI Chat
- Skills 分槽
- `check_request`
- 命中 `page_check`
- `runner_service` 执行
- 返回结构化结果与证据

适用场景：

- 页面、菜单、状态检查
- 数据存在性检查
- 高频调度型巡检

正式对象：

- `page_check`
- `module_plan`

### 3.2 路径二：复杂功能测试路径

新增主链：

- 浏览器示教/录制
- 上传示教包
- 平台 ingest / resolve / normalize / align / compile
- 自动生成正式任务草案
- 用户一次总确认
- 平台执行与调度

适用场景：

- 跨页面业务功能测试
- 含有限写操作的功能验收
- 新功能上线后的快速测试任务生成

正式对象：

- `action_block`
- `assertion_block`
- `flow_plan`

### 3.3 统一内核

两条产品路径共享：

- 页面与菜单事实
- 页面资产
- 定位证据
- 认证治理
- 执行器
- 调度器
- 结果审计模型

---

## 4. 核心设计原则

### 4.1 资产优先，不以录制轨迹为真相

录制轨迹、Midscene 插件生成的脚本、截图、trace 都只是编译输入或派生产物，不是正式执行真相。

正式真相应保持为：

- 巡检路径：`page_check + module_plan`
- 功能测试路径：`action_block + assertion_block + flow_plan`

### 4.2 AI 是编译器与修复器，不是正式执行中的自由规划者

AI 的作用主要在：

- 轨迹语义切段
- 资产对齐
- 动作块/断言块抽象
- flow 草案生成
- 失败后的有限修复建议

不适合让 AI 在正式执行时每一步自由临场规划。

### 4.3 录制不是重放

录制的作用是：

- 捕获示教证据
- 帮助编译正式对象
- 提供调试与回溯材料

录制不应直接等价于“以后一直重放这段脚本”。

### 4.4 功能测试允许写，但必须受控

平台不再限定功能测试只能只读，但必须：

- 绑定测试身份
- 标注动作风险等级
- 输出影响摘要
- 支持测试数据清理策略

### 4.5 复杂功能测试以线性 flow 为起点

第一阶段不做完整流程引擎，只支持：

- 单系统
- 线性步骤
- 顺序执行

不引入：

- 分支
- 循环
- 并行
- 动态子流程

---

## 5. 正式对象模型

### 5.1 巡检对象

保持现有对象：

- `page_check`
- `module_plan`

继续用于：

- 页面级检查
- 数据状态检查
- 高频巡检调度

### 5.2 新增动作块：`action_block`

`action_block` 表示一个可复用的业务动作块，通常落在单页面或单状态边界内。

典型示例：

- 进入某菜单并打开页面
- 在列表页输入条件并查询
- 点击某行进入详情
- 在详情页点击“关联订单”
- 使用测试账号提交测试表单

建议字段：

- `system_id`
- `page_asset_id`
- `block_code`
- `action_type`
- `input_schema`
- `precondition_schema`
- `result_schema`
- `risk_level`
- `state_signature`
- `state_context`
- `locator_bundle`
- `navigation_target_ref`
- `module_steps`

### 5.3 新增断言块：`assertion_block`

`assertion_block` 表示一个可复用的验证块。

典型示例：

- 页面打开成功
- 某状态已切换成功
- 某字段存在或值匹配
- 提交成功提示出现
- 跨页业务对象一致

建议字段：

- `system_id`
- `page_asset_id`
- `block_code`
- `assertion_type`
- `input_schema`
- `assertion_schema`
- `evidence_policy`
- `failure_category_map`
- `state_signature`
- `locator_bundle`

### 5.4 新增跨页面正式对象：`flow_plan`

`flow_plan` 表示由多个 `action_block` 与 `assertion_block` 顺序组合而成的跨页面功能测试任务。

建议字段：

- `system_id`
- `flow_code`
- `flow_version`
- `goal`
- `environment_scope`
- `identity_policy`
- `risk_level`
- `input_schema`
- `cleanup_policy`
- `steps_json`

### 5.5 对象关系

- `page_asset` 可关联多个 `page_check`
- `page_asset` 可关联多个 `action_block`
- `page_asset` 可关联多个 `assertion_block`
- `flow_plan` 引用多个 block
- `published_job` 后续既可调度 `page_check`，也可调度 `flow_plan`

---

## 6. 示教包设计

### 6.1 录制端策略

前端示教计划复用并二开 Midscene 浏览器录制插件。

插件负责：

- 登录后才能使用录制能力
- 采集用户在页面中的示教行为
- 生成 Playwright 脚本与结构化示教证据

平台不直接信任插件上报的“系统/环境/身份”声明，而是根据：

- 访问过的 URL
- 插件登录平台用户
- 数据库存储的系统环境映射

反查最终归属。

### 6.2 示教包最小契约

平台上传物不是单个脚本文件，而是 `demonstration_bundle`。

建议顶层结构：

- `manifest`
- `steps`
- `artifacts`
- `script`

#### `manifest`

记录事实线索，而不是最终真相：

- `bundle_version`
- `operator_platform_user_id`
- `capture_source`
- `task_goal`
- `start_url`
- `final_url`
- `visited_urls`
- `started_at`
- `finished_at`

#### `steps`

记录结构化示教步骤：

- `seq`
- `kind`
- `url_before`
- `url_after`
- `title_before`
- `title_after`
- `route_hint`
- `target`
- `input_payload`
- `expected_hint`
- `screenshot_ref`
- `timestamp`

建议 MVP 支持的 `kind`：

- `navigate`
- `click`
- `input`
- `select`
- `submit`
- `assert_hint`
- `state_change`
- `wait`

#### `target`

应支持结构化目标，而不是只收单一 selector：

- `role`
- `text`
- `label`
- `name`
- `placeholder`
- `locator`
- `locator_candidates`
- `context_text`
- `element_type`

#### `artifacts`

MVP 先支持：

- `screenshot`
- `trace`
- `dom_snapshot`

#### `script`

保留录制端生成的 Playwright 脚本，用于：

- 调试
- 回放
- 辅助编译
- 导出

但不作为正式执行真相。

---

## 7. 平台流水线

平台接收示教包后，建议走五段流水线：

1. `ingest`
2. `resolve`
3. `normalize`
4. `align`
5. `compile`

### 7.1 Ingest

职责：

- 校验示教包结构
- 落原始 bundle
- 存储 artifacts
- 生成 `demonstration_id`

不负责：

- 业务语义解析
- 资产对齐
- 正式对象生成

### 7.2 Resolve

职责：

- 根据 URL 与登录平台用户识别系统
- 识别环境
- 识别测试身份
- 输出解析置信度与警告

建议输出：

- `resolved_system_id`
- `resolved_environment_id`
- `resolved_identity_profile_id`
- `resolution_confidence`
- `resolution_warnings`

### 7.3 Normalize

职责：

- 把录制插件原始事件转成平台统一 step 语义
- 屏蔽 Midscene 录制插件具体实现细节

输出统一 step 字段：

- `kind`
- `url_before/url_after`
- `route_hint`
- `locator_candidates`
- `input_payload`
- `artifact_refs`

### 7.4 Align

职责：

- 将 normalized steps 与现有资产对齐

优先对齐对象：

- `Page`
- `MenuNode`
- `NavigationTarget`
- `PageElement.locator_candidates`
- `PageAsset`
- 既有 `PageCheck`
- 既有 block

输出：

- `matched_assets`
- `matched_navigation_targets`
- `matched_existing_blocks`
- `unmatched_segments`
- `alignment_confidence`
- `alignment_warnings`

### 7.5 Compile

职责：

- 轨迹切段
- 生成新的 `action_block` 草案
- 生成新的 `assertion_block` 草案
- 复用已有 `page_check` / 既有 block
- 生成线性 `flow_plan draft`
- 推断风险级别、清理策略、输入输出变量

输出：

- `action_block` drafts
- `assertion_block` drafts
- `flow_plan draft`
- `compile_summary`
- `compile_warnings`

---

## 8. 正式执行链设计

### 8.1 执行前校验

正式执行前，平台应先校验：

- 当前对象是 `page_check` 还是 `flow_plan`
- 当前环境是否允许执行
- 当前测试身份是否有效
- 是否包含禁止动作
- 参数是否完整
- 清理策略是否满足要求

### 8.2 测试身份模型

建议在认证侧新增测试身份抽象，例如：

- `execution_identity_profile`

至少表达：

- 对应系统与环境
- 可用测试账号
- 允许动作等级
- 是否可用于自动化功能测试
- 绑定的认证态

### 8.3 动作风险分级

建议每个 `action_block` 带风险级别：

- `readonly`
- `safe_test_write`
- `guarded_write`
- `forbidden`

### 8.4 分步执行

`flow_plan` 执行时，按 block 顺序执行：

- `action_block`
- `assertion_block`
- `action_block`
- `assertion_block`

每一步需沉淀：

- 输入参数
- 页面上下文
- 结果状态
- artifact
- failure category

### 8.5 影响摘要

允许写操作后，必须新增影响摘要能力，至少输出：

- 创建了哪些对象
- 修改了哪些对象
- 删除了哪些对象
- 是否命中测试数据标记
- 是否需要清理
- 清理是否成功

### 8.6 清理策略

建议支持三类清理策略：

- `no_cleanup`
- `best_effort_cleanup`
- `must_cleanup`

---

## 9. 子域职责划分

### 9.1 `control_plane`

负责：

- 接收示教包 ingest 请求
- 发起 resolve / normalize / compile 流程
- 返回编译状态
- 提供总确认入口
- 发布正式对象
- 发起试跑或调度

不负责：

- 解析脚本细节
- 资产对齐
- 运行浏览器

### 9.2 `auth_service`

负责：

- 测试身份模型
- 测试账号认证态刷新
- 身份风险等级与环境绑定
- 服务端认证注入

### 9.3 `crawler_service`

继续负责：

- 页面、菜单、状态入口、元素候选的事实采集
- `locator_candidates`
- `state_signature`
- `navigation_targets`

不负责：

- 消费示教包
- 编译 flow
- 正式功能测试执行

### 9.4 `asset_compiler`

新增职责：

- `demonstration -> action_block/assertion_block/flow_plan draft`

这是新能力的核心落点。

### 9.5 `runner_service`

新增职责：

- 执行 `flow_plan`
- 执行 block
- 执行前探测
- 影响摘要
- 清理动作

但仍保持：

- 只执行被批准的计划
- 不临场解释自然语言

---

## 10. 前端与交互设计

### 10.1 交互目标

尽量实现：

- 自动生成草案
- 用户只做一次总确认

### 10.2 三个核心界面

第一阶段建议前端只做：

1. `示教发起页`
2. `示教回放与编译页`
3. `总确认页`

而不优先做：

- 拖拉拽工作流编辑器
- 节点画布
- DSL 编排器

### 10.3 总确认页应展示的内容

建议展示：

- 任务目标
- 页面链路摘要
- 关键动作摘要
- 关键断言摘要
- 测试身份与环境
- 风险与影响
- 立即试跑 / 保存 / 发布

高级信息可折叠展示：

- block 列表
- 对齐结果
- 编译置信度
- 定位证据

---

## 11. MVP 范围

### 11.1 MVP 支持范围

MVP 仅支持：

- 单系统内
- 线性流程
- 菜单跳转 + 页内跳转
- 有限动作集
- 受控写操作
- 手动试跑为主

### 11.2 MVP 不支持

MVP 暂不支持：

- 跨系统流程
- 条件分支
- 循环与并行
- 高副作用动作
- 全自动修复
- 大规模复杂调度

### 11.3 MVP 最小闭环

1. 用户登录录制插件
2. 录制一条单系统内的功能流
3. 上传示教包
4. 平台生成 `action_block/assertion_block/flow_plan` 草案
5. 用户一次总确认
6. 使用测试身份手动试跑
7. 输出证据、影响摘要与清理摘要
8. 保存为正式 flow

---

## 12. 风险与缓解

### 12.1 录制质量不足

风险：

- 仅靠脚本或原始点击日志难以稳定编译

缓解：

- 示教包必须包含结构化 step、截图和 locator candidates

### 12.2 资产对齐失败

风险：

- 新功能页面尚未被 crawl 完整采到

缓解：

- compile 支持部分成功
- 未对齐段生成新增 block 草案
- 允许触发补采集

### 12.3 写操作风险过高

风险：

- 测试任务误触发高副作用动作

缓解：

- 动作分级
- 测试身份绑定
- `forbidden` 动作硬阻断

### 12.4 范围膨胀

风险：

- 过早引入完整工作流语义，失去聚焦

缓解：

- MVP 严格限制为单系统线性流程

---

## 13. 结论

本设计确认，`Runlet` 面向企业级自动化仿真巡检与测试时，不应在“工作流编排”“录制重放”“纯 AI 动态执行”之间做简单二选一，而应采用：

**双路径产品形态 + 统一资产执行内核**

具体为：

- 路径一：轻量巡检，继续以 `page_check + module_plan` 为正式对象
- 路径二：示教驱动的功能测试编译链，以 `action_block + assertion_block + flow_plan` 为正式对象

录制插件可复用 Midscene 并进行二开，但平台必须坚持：

- 脚本不是系统真相
- 示教包是编译输入
- 正式真相始终是平台资产与正式计划对象

---

## 14. 后续实施建议

1. 先补“系统环境映射”和“测试身份”模型。
2. 定义并落地 `demonstration_bundle` API 与落库模型。
3. 在 `asset_compiler` 中新增 `demonstration -> draft` 编译路径。
4. 先实现线性 `flow_plan` 的手动试跑。
5. 待 MVP 验证通过后，再评估调度、修复与更复杂流程能力。
