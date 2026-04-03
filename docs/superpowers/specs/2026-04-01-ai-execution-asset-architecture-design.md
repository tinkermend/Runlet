# AI 执行资产架构设计规范

**日期：** 2026-04-01
**作者：** Codex
**状态：** 草案

---

## 执行摘要 (Executive Summary)

本规范定义了 `web-router-map` 项目的新执行架构。核心变化是将当前以爬取为中心的数据模型分离为三个层级：

- **原始采集事实层**：针对系统、菜单、页面和元素的原始爬取事实。
- **编译执行资产层**：针对页面级检查和可复用动作模块的编译后执行资产。
- **统一执行控制面**：通过服务 API 暴露的统一执行入口。

目标运行模式是“双轨执行”：

- **高频和核心页面**：通过预编译的页面检查运行，以实现更低的时延和更强的安全控制。
- **长尾或过期页面**：回推到基于紧凑页面上下文和可复用模块的受控运行时装配。

本设计旨在解决当前存在的三个问题：

1. **MCP 返回数据过多**：因为运行时调用方仍然依赖原始树结构。
2. **LLM 生成 Playwright 脚本过慢**：每次都从头开始生成。
3. **固化生成的脚本不安全且不可靠**：当身份验证检索留给调用方处理时，安全性无法保障。

---

## 问题陈述 (Problem Statement)

现有架构已经捕获了身份验证状态、路由树、页面元数据和可操作元素。虽然这一基础很有用，但运行时路径仍将爬取数据库视为下游 AI 工具的直接 Prompt 来源。

这导致了几个结构性问题：

1. **检索过载 (Retrieval overload)**
   用户意图映射到原始的系统/页面/元素记录，因此即使是精简后的 MCP 响应，对于运行时执行来说仍然携带了过多的上下文。

2. **生成延迟 (Generation latency)**
   运行时 Playwright 生成仍在一次处理中完成意图解释、检索解释、导航规划、定位器选择和身份验证组合。

3. **不安全的认证边界 (Unsafe auth boundaries)**
   生成的脚本和工具调用方离原始的 `storage_state` 和 Token 材质过近，这使得脚本固化、审计和强制认证行为难以保证。

4. **弱更新同步 (Weak update synchronization)**
   系统虽然会爬取新事实，但尚未将执行资产作为一等版本化对象进行管理，因此页面更改无法清晰地传播到可复用的检查中。

---

## 设计目标 (Design Goals)

### 主要目标

- 支持**双轨执行模型**：
  - 针对核心和高频检查的预编译资产。
  - 针对长尾检查的受控运行时装配。
- 使 **Service API** 成为唯一的官方执行入口点。
- 从“原始树检索”转向“**页面级可执行资产**”。
- 对所有正式执行强制实施**服务端身份验证注入**。
- 引入**资产新鲜度和漂移管理**，使爬取变更能够使执行资产失效或触发刷新。

### 次要目标

- 保留现有的爬取 Schema 作为发现事实的真理来源。
- 保持 MCP 对轻量级发现、解释和兼容性的有用性。
- 保持 CLI 对操作员工作流、批处理作业和调试的有用性。

### 非目标 (Non-Goals)

- 在本次设计迭代中支持非 Vue/非 React 系统。
- 为每个页面构建完全自由形式的业务工作流自动化。
- 用另一个执行引擎替换 Playwright。
- 向外部 AI 客户端广泛暴露原始身份验证材质。

---

## 架构概览 (Architecture Overview)

### 目标层级

1. **原始爬取事实层 (Raw Crawl Fact Layer)**
   存储发现的系统、认证、菜单、页面和元素事实。

2. **执行资产层 (Execution Asset Layer)**
   存储从爬取快照派生的编译后页面级检查和可复用动作模块。

3. **执行控制层 (Execution Control Layer)**
   接受结构化的检查请求，选择执行路径，注入身份验证并运行 Playwright。

4. **访问层 (Access Layer)**
   MCP、CLI 和 Skills 成为围绕控制层的薄客户端，而不是独立的执行编排器。

### 职责边界

#### 原始爬取事实层

该层回答：“目标系统当前看起来是什么样子的？”

包括：
- `web_systems`
- `storage_states`
- `nav_menus`
- `app_pages`
- `ui_elements`
- 相关的爬取日志和验证元数据

该层不定义最终的运行时行为。

#### 执行资产层

该层回答：“针对此页面我们可以运行哪些稳定的检查？”

存储：
- 页面级执行资产
- 这些资产下的标准检查
- 可复用动作模块
- 资产与快照的版本关系

这是预编译执行的主要运行时目标。

#### 执行控制层

该层回答：“对于此请求，应该针对哪个版本、使用什么认证运行什么内容？”

负责：
- 意图归一化
- 资产查找
- 回退路由
- 认证刷新与认证注入
- 执行结果记录
- 在需要时触发重新爬取或重新编译

#### 访问层

该层暴露受限接口：
- **Service API**：用于正式执行。
- **MCP**：用于发现和状态查找。
- **CLI**：用于操作员工作流。
- **Skills**：仅用于用户意图翻译。

---

## 数据模型设计 (Data Model Design)

### 保留现有的事实模型

现有层级结构作为事实层依然有效：
- `web_systems`
- `storage_states`
- `nav_menus`
- `app_pages`
- `ui_elements`

这些模型继续存储爬取时的真实情况，例如：
- 框架类型
- 基础 URL 和路由路径
- 菜单层级
- 页面摘要
- 定位器稳定性和有用性
- 认证状态有效性

### 新资产模型 (New Asset Models)

#### `page_assets`

表示一个页面的版本化执行资产。

建议字段：
- `id`
- `system_id`
- `page_id`
- `asset_key`
- `asset_version`
- `status` (`draft`, `ready`, `suspect`, `stale`, `disabled`)
- `priority`
- `freshness_level`
- `compiled_from_snapshot_id`
- `compiled_at`
- `last_verified_at`

#### `page_checks`

表示一个页面资产下可用的标准检查。

示例：
- `page_open`
- `table_render`
- `open_create_modal`
- `search_submit`

建议字段：
- `id`
- `page_asset_id`
- `check_code`
- `goal`
- `input_schema`
- `expected_assertions`
- `module_plan`
- `script_template_ref`
- `success_rate`
- `failure_budget`
- `last_verified_at`

#### `action_modules`

表示可复用的低级执行模块。

示例：
- `auth.inject_state`
- `nav.menu_chain`
- `page.wait_ready`
- `table.assert_visible`
- `modal.open_primary_action`

建议字段：
- `id`
- `module_code`
- `module_version`
- `framework_scope`
- `input_contract`
- `runtime_contract`
- `status`

#### `asset_snapshots`

表示用于编译资产的爬取快照和结构指纹。

建议字段：
- `id`
- `system_id`
- `crawl_log_id`
- `structure_hash`
- `navigation_hash`
- `key_locator_hash`
- `semantic_summary_hash`
- `compiled_at`
- `diff_score_vs_previous`

### 意图映射模型 (Intent Mapping Models)

#### `intent_aliases`

该层将用户语言与原始页面和元素树解耦。

建议字段：
- `id`
- `system_alias`
- `page_alias`
- `check_alias`
- `route_hint`
- `asset_key`
- `confidence`
- `source`

运行时应在读取元素级上下文之前，针对此模型解析用户措辞。

### 核心原则

数据库应明确存储三类对象：
1. 原始事实
2. 编译后的执行资产
3. 意图映射别名

这些类别绝不能在运行时 MCP 负载中临时重组。

---

## 运行时执行流 (Runtime Execution Flow)

### 请求契约 (Request Contract)

正式执行请求应由服务驱动且结构化，例如：
- `system_hint`
- `page_hint`
- `check_goal`
- `strictness`
- `time_budget_ms`
- `request_source`

自然语言解释应在执行开始前停止。

### 执行决策流水线 (Execution Decision Pipeline)

1. 将意图归一化为系统/页面/检查候选对象。
2. 解析匹配的 `page_asset` 和 `page_check`。
3. 选择执行路径：
   - 当就绪资产存在时使用 `precompiled`（预编译）。
   - 当资产缺失、不完整或允许降级时使用 `realtime`（实时）。
4. 获取并验证认证状态。
5. 在服务端注入认证。
6. 通过编译后的模块计划或受控运行时装配执行 Playwright。
7. 记录执行输出、耗时和失败类别。
8. 如果策略需要，触发重新爬取或重新编译。

### 预编译轨道 (Precompiled Track)

预编译路径不应主要存储自由形式的脚本。它应存储结构化的模块计划，例如：
- `auth.inject_state`
- `nav.menu_chain`
- `page.wait_ready`
- `assert.title_contains`
- `assert.table_visible`

这将运行时的 LLM 工作从完整的脚本生成降级为参数绑定。

### 实时轨道 (Realtime Track)

仅在以下情况下允许实时生成：
- 不存在匹配的页面资产。
- 存在页面资产但缺失请求的检查。
- 资产已过期但允许降级。
- 请求非常具体且属于长尾需求。

实时装配必须使用严密受限的输入：
- 一个解析后的页面。
- 一个导航计划。
- 一个以目标为导向的定位器包。
- 一个小的动作模块集。

默认情况下不得使用完整的原始元素树。

---

## 身份验证与安全模型 (Authentication and Security Model)

### 原则

身份验证必须由执行服务强制执行，而不是由生成的脚本或外部工具调用方执行。

### 要求的行为

- 通过 `system_id` 解析最新的有效 `storage_state`。
- 在执行前验证过期时间和有效性。
- 在策略允许时触发刷新。
- 在服务端将认证注入 Playwright 浏览器上下文。
- 避免向全上游 AI 层广泛暴露原始认证状态。

### 脚本固化规则 (Script Solidification Rule)

如果一个检查被导出或固化，它必须引用受控的认证模块，而不是直接嵌入 Token 检索或 Token 材质。

这确保了：
- 可重复执行。
- 可审计性。
- 一致的认证强制执行。
- 更低的 Token 泄露风险。

---

## 漂移检测与资产新鲜度 (Drift Detection and Asset Freshness)

### 资产同步单元

系统应同步**资产有效性**，而不仅仅是原始脚本。

### 爬取派生的指纹

每次相关的爬取都应至少产出以下方面的结构指纹：
- 导航链
- 路由标识
- 关键定位器集
- 页面语义摘要

### 资产健康状态 (Asset Health States)

建议状态：
- `safe`（安全）：资产继续受信任。
- `suspect`（可疑）：轻微结构漂移，需要后台重新验证。
- `stale`（陈旧）：关键导航/断言点已更改，需要重新编译。

### 更新流水线

爬取完成后：
1. 持久化新的事实快照。
2. 计算与上一个快照的差异。
3. 识别受影响的页面资产。
4. 重新验证 `suspect` 或 `stale` 检查。
5. 当模块计划仍可安全派生时自动重新编译。
6. 降级或禁用无法修复的资产。

该流水线通过版本化的资产生命周期管理取代了传统的手动大批量脚本重写。

### 运行时策略

使用分级策略：
- **核心系统 / 核心页面**：在资产陈旧时拦截并要求刷新。
- **长尾页面**：在策略允许时允许降级的运行时执行。

这符合所选的混合严格性策略。

---

## 接口重新分配 (Interface Reallocation)

### Service API

Service API 成为唯一的官方控制面，用于：
- 执行请求。
- 认证受控的运行时执行。
- 资产状态转换。
- 重新爬取 / 重新编译触发。
- 审计日志记录与报告。

### MCP

MCP 应专注于轻量级发现和解释：
- 查找系统和页面。
- 列出可用检查。
- 显示资产状态。
- 返回最近的执行摘要。
- 在需要时暴露调试追踪信息。

MCP 可以提供一个薄的“请求执行”工具，但该工具应代理到 Service API，而不是独立构建执行包。

### CLI

CLI 应支持操作员和工程任务，例如：
- 刷新认证状态。
- 触发爬取。
- 触发资产编译。
- 比较快照差异。
- 验证页面资产。
- 导出调试脚本。

CLI 不应作为面向用户的主要运行时界面。

### Skills

Skills 应负责：
- 解析用户请求。
- 构建结构化的执行请求。
- 调用 Service API。
- 将结果翻译回用户语言。

Skills 不应从原始爬取上下文中组装完整的 Playwright 脚本路径。

---

## 推广策略 (Rollout Strategy)

### 第一阶段：保留现有爬取并增加资产模型

- 保持当前的爬取和认证刷新流程不变。
- 增加新的资产层表和编译元数据。
- 保持当前 MCP 工具运行以实现向后兼容。

### 第二阶段：引入页面资产编译

- 将有限的核心高频页面编译为页面资产。
- 定义首批标准检查，如 `page_open`、`table_render` 和 `open_create_modal`。
- 创建模块计划存储与验证机制。

### 第三阶段：将运行时执行移至 Service API

- 增加结构化执行端点。
- 使 Skills 调用 Service API。
- 将 MCP 保留为仅检索的兼容层。

### 第四阶段：引入漂移感知的重新验证

- 计算快照指纹。
- 自动将资产标记为 `safe`、`suspect` 或 `stale`。
- 自动化选择性的重新编译和降级行为。

---

## 错误处理与可观测性 (Error Handling and Observability)

每次执行结果都应捕获：
- 解析后的系统/页面/检查。
- 选择的执行路径（`precompiled` 或 `realtime`）。
- 认证结果（`reused`、`refreshed`、`blocked`）。
- 资产版本或快照版本。
- 执行耗时。
- 失败类别。
- 是否触发了重新爬取或重新编译。

建议的失败类别：
- `auth_invalid`（认证无效）
- `navigation_failed`（导航失败）
- `locator_drift`（定位器漂移）
- `route_mismatch`（路由不匹配）
- `assertion_failed`（断言失败）
- `asset_stale_blocked`（资产陈旧被拦截）
- `runtime_generation_failed`（运行时生成失败）

这种分类对于资产治理和可靠性调优是必要的。

---

## 测试策略 (Testing Strategy)

从本规范派生的实施计划应至少包括：
- 针对资产解析和执行路径选择的单元测试。
- 针对认证注入策略强制执行的单元测试。
- 针对漂移分类和资产状态转换的单元测试。
- 针对执行请求契约的服务级测试。
- 针对存储的爬取快照运行页面资产执行的集成测试。
- 证明生成的或导出的检查无法绕过受控认证注入的回归测试。

本项目应继续遵循仓库规则，即完成的开发变更需包含单元测试覆盖和变更日志更新。

---

## 待解决问题 (Open Questions)

这些问题不会阻碍规划，但必须在实施设计期间解决：
1. 页面资产编译是仅存储归一化的 JSON 模块计划，还是也存储渲染后的 Playwright 代码以供调试导出？
2. 是从历史爬取数据中激进地回填 `intent_aliases`，还是采用人工管理方式？
3. 核心页面分类是存储在 `web_systems`、`page_assets` 还是单独的策略表中？
4. 导出的调试脚本是按需生成还是作为派生伪影进行缓存？

---

## 建议 (Recommendation)

采用本规范中描述的以 Service-API 为中心的双轨架构。

具体而言：
- 将目前的爬取数据库作为事实仓库保留。
- 在其之上增加一个编译后的执行资产层。
- 将正式执行权限移至 Service API。
- 将 MCP 的职责收缩至发现和兼容性。
- 使用页面级资产作为主要执行单元，并将模块作为组合基座。

针对目前的 Vue/React 专用项目范围，该设计在时延、复用、安全和更新弹性之间实现了最佳平衡。

