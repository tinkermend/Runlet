# Runlet 与 Midscene、Playwright CLI、bb-browser、browser-use、Cypress、agent-browser 对比分析矩阵

## 1. 文档目的

本文用于从产品定位、技术路线、企业落地适配度三个层面对比以下项目：

- `Runlet`（当前项目）
- `Midscene`
- `Playwright CLI`
- `bb-browser`
- `browser-use`
- `Cypress`
- `agent-browser`
- `https://github.com/browserbase/stagehand`
- `https://github.com/Skyvern-AI/skyvern`

本文重点不是比较“谁更强”，而是比较：

1. 各自解决的是哪一类问题。
2. 哪些能力适合沉淀为平台能力。
3. 哪些能力更适合作为底层工具或临时执行器。
4. 当前 `Runlet` 应该向哪些方向吸收能力，哪些方向不应偏航。

## 2. 评估口径

### 2.1 时间口径

- 本文基于 `2026-04-05` 时点的公开资料与当前仓库实现。

### 2.2 星级口径

- 最高 `5` 星。
- 星级不是“社区热度”，而是站在“企业级浏览器执行平台建设”视角下的综合判断。
- 星级同时考虑公开能力、工程落地成本、治理边界与长期维护性。

### 2.3 名称口径

- `Playwright CLI` 指官方 `@playwright/cli` 的 coding agents CLI。
- `bb-browser` 指 `epiral/bb-browser`，不是 Buildbarn 的同名项目。
- `agent-browser` 指 `vercel-labs/agent-browser`。

## 3. 当前项目 Runlet 的定位抽象

基于当前仓库，可以把 `Runlet` 的主线总结为：

- 检查资产是主模型，不把自由脚本文本当系统真相。
- 正式执行统一走 `control_plane`。
- 正式认证统一由服务端注入。
- 运行时默认从 `intent_aliases -> page_assets -> page_checks` 命中。
- 未命中时只允许进入页面级 `realtime_probe`，不放开成无限制自由浏览器 Agent。

这意味着 `Runlet` 的本质定位不是“通用浏览器 AI 助手”，而是：

**面向企业后台场景的资产化、可调度、可审计的浏览器检查执行平台。**

## 4. 一句话定位矩阵

| 项目 | 一句话定位 | 更像什么 |
|------|------|------|
| `Runlet` | 企业级浏览器检查与调度治理平台 | 平台层 |
| `Midscene` | 视觉驱动、跨 Web/移动端的 AI 自动化 SDK | AI 操作层 |
| `Playwright CLI` | 面向 coding agent 的低层浏览器 CLI | 执行底座 |
| `bb-browser` | 复用真实浏览器登录态，把网站变成 CLI/API 的工具 | 用户态接入层 |
| `browser-use` | 通用网页 Agent 框架 | Agent 层 |
| `Cypress` | 前端研发主导的测试框架 | 测试工程层 |
| `agent-browser` | 面向 AI agent 的浏览器 CLI/MCP | Agent-friendly 执行底座 |

## 5. 架构路线对比

| 维度 | Runlet | Midscene | Playwright CLI | bb-browser | browser-use | Cypress | agent-browser |
|------|------|------|------|------|------|------|------|
| 主体抽象 | 资产、计划、执行、调度 | 视觉任务与 UI 操作 | 浏览器会话与命令 | 真实浏览器标签页与站点适配器 | 任务、Agent、Browser、Tools | 测试用例、断言、浏览器 | 浏览器会话、snapshot refs、CLI/MCP |
| 执行真相 | `page_check + module_plan + execution_run` | AI 指令与视觉操作 | CLI 命令与浏览器状态 | 用户真实浏览器会话 | Agent 决策轨迹 | 测试代码与断言 | CLI 命令与 snapshot refs |
| 是否有中心控制面 | 有 | 无 | 无 | 无 | 弱 | 弱 | 无 |
| 是否有内建调度治理 | 有 | 弱 | 无 | 无 | 弱 | 依赖 CI | 无 |
| 是否强调资产沉淀 | 强 | 弱 | 无 | 弱 | 弱 | 中 | 弱 |
| 是否允许自由推理 | 受控、有限 | 强 | 中 | 中 | 强 | 弱 | 中 |

## 6. 能力星级矩阵

### 6.1 综合能力星级

| 能力维度 | Runlet | Midscene | Playwright CLI | bb-browser | browser-use | Cypress | agent-browser |
|------|---:|---:|---:|---:|---:|---:|---:|
| 自然语言直接驱动 | 2 | 5 | 3 | 4 | 5 | 1 | 4 |
| 执行确定性与可复现 | 4 | 3 | 5 | 3 | 2 | 5 | 4 |
| 企业治理与权限边界 | 5 | 2 | 2 | 1 | 2 | 2 | 1 |
| 认证治理能力 | 5 | 2 | 3 | 5 | 4 | 3 | 3 |
| 结果审计与证据沉淀 | 4 | 4 | 5 | 3 | 3 | 4 | 4 |
| 调度与长期运行 | 5 | 2 | 2 | 2 | 3 | 4 | 2 |
| 前端测试工程化 | 3 | 4 | 4 | 1 | 2 | 5 | 3 |
| 通用网页 Agent 能力 | 2 | 4 | 4 | 4 | 5 | 2 | 5 |
| 复杂登录站点适应性 | 4 | 3 | 4 | 5 | 4 | 3 | 4 |
| 跨平台自动化（Web/移动） | 1 | 5 | 2 | 2 | 2 | 2 | 3 |
| 结构化业务数据断言 | 5 | 3 | 3 | 2 | 2 | 3 | 2 |
| 作为企业正式执行主链的适配度 | 5 | 2 | 3 | 1 | 2 | 3 | 2 |

### 6.2 星级解释

#### `Runlet`

- 长板：治理、审计、调度、资产化、服务端认证注入、结构化数据断言。
- 短板：开放式 Agent 能力弱，不适合无限制自由探索。

#### `Midscene`

- 长板：自然语言、视觉驱动、跨 Web/Android/iOS、调试回放体验好。
- 短板：平台治理与企业控制面较弱，确定性依赖视觉模型与页面稳定度。

#### `Playwright CLI`

- 长板：低层能力完整，命令面广，trace/video/network/storage/session 能力强。
- 短板：它是工具，不是平台；没有业务治理和正式执行边界。

#### `bb-browser`

- 长板：复用真实浏览器登录态、复杂网站与反爬场景很强、网站即 API。
- 短板：企业正式执行治理弱，不适合作为服务端统一认证的主链。

#### `browser-use`

- 长板：通用任务执行、Agent 规划、多工具扩展、云端生产化配套较丰富。
- 短板：黑盒性更高，结果可复现性与治理边界不如资产驱动架构。

#### `Cypress`

- 长板：前端测试工程化、E2E 与组件测试成熟、团队协作与 CI 友好。
- 短板：不是通用浏览器 Agent，也不是企业浏览器治理平台。

#### `agent-browser`

- 长板：对 agent 友好，snapshot ref、HAR、network、cookies/storage、CLI/MCP 完整。
- 短板：更像执行底座，不是业务平台。

## 7. 适合的场景矩阵

### 7.1 更适合的场景

| 场景 | Runlet | Midscene | Playwright CLI | bb-browser | browser-use | Cypress | agent-browser |
|------|------|------|------|------|------|------|------|
| 企业后台只读巡检 | 强适合 | 适合 | 适合 | 一般 | 一般 | 适合 | 适合 |
| 参数化数据断言 | 强适合 | 一般 | 一般 | 较弱 | 较弱 | 一般 | 较弱 |
| 自然语言驱动业务检查 | 适合 | 强适合 | 一般 | 适合 | 强适合 | 较弱 | 适合 |
| 开放式网页任务执行 | 较弱 | 适合 | 适合 | 适合 | 强适合 | 较弱 | 强适合 |
| 前端 E2E 回归测试 | 一般 | 适合 | 强适合 | 较弱 | 一般 | 强适合 | 适合 |
| 组件测试 | 较弱 | 一般 | 一般 | 不适合 | 不适合 | 强适合 | 不适合 |
| 复杂登录站点自动化 | 适合 | 一般 | 适合 | 强适合 | 适合 | 一般 | 适合 |
| 服务端统一认证执行 | 强适合 | 较弱 | 一般 | 不适合 | 一般 | 一般 | 一般 |
| 定时调度巡检 | 强适合 | 一般 | 一般 | 较弱 | 一般 | 适合 | 较弱 |
| 多端统一自动化 | 较弱 | 强适合 | 较弱 | 较弱 | 较弱 | 较弱 | 一般 |

### 7.2 不太适合的场景

| 项目 | 不太适合的场景 |
|------|------|
| `Runlet` | 开放式自由探索、复杂写操作、无稳定资产的网站、跨站长链路自由业务编排 |
| `Midscene` | 要求高确定性、强治理、强调度、强资产版本绑定的正式执行主链 |
| `Playwright CLI` | 直接承担企业平台控制面、调度治理、业务资产管理 |
| `bb-browser` | 服务端统一认证、严格隔离的正式执行链、可审计审批链 |
| `browser-use` | 需要高度可复现、强规则边界、稳定回归的企业业务检查 |
| `Cypress` | 通用网页 Agent、跨站任务代理、自然语言临场探索 |
| `agent-browser` | 企业正式执行控制面、资产编译与调度治理 |

## 8. 逐项详细分析

### 8.1 Runlet

#### 更适合

- 企业内部 Vue/React 管理后台。
- “页面是否可达、表格是否渲染、当前是否有数据、某条记录是否存在”这类只读检查。
- 需要从一次执行沉淀为长期调度对象的场景。
- 需要认证统一由服务端注入、不能依赖个人本地会话的场景。

#### 不太适合

- 让 AI 看到一个陌生网站后临场自由探索、自由推理并完成复杂任务。
- 破坏性操作主链，例如创建、审批、删除、付款。
- 频繁改版、无法沉淀稳定资产的页面。

#### 判断理由

- 当前主线明确要求资产优先、control plane 统一编排、服务端统一认证注入。
- `realtime_probe` 只是页面级受控降级，不是通用自由执行器。

### 8.2 Midscene

#### 更适合

- 需要“自然语言 + 视觉理解 + UI 操作”的自动化。
- DOM 不稳定、视觉布局更可靠的界面。
- Web、Android、iOS 混合场景。
- 快速 PoC、AI 驱动测试、跨端自动化实验。

#### 不太适合

- 把它直接作为企业正式执行平台主链。
- 强依赖审批、审计、计划、资产版本绑定的场景。

#### 判断理由

- Midscene 官方明确强调 vision-driven、自然语言、JavaScript SDK/YAML、Web+移动端+MCP。
- 它更强在“AI 操作界面”，而不是“平台治理”。

### 8.3 Playwright CLI

#### 更适合

- 给 coding agent 一个强大的底层浏览器工具。
- 需要 snapshot refs、截图、PDF、network、storage、trace、video、named session。
- 希望用确定性的命令而不是纯视觉模型驱动浏览器。

#### 不太适合

- 单独拿来承载企业级业务检查平台。
- 单独承担资产编译、调度、权限治理、业务审计。

#### 判断理由

- Playwright CLI 官方能力非常完整，适合作为执行底座。
- 但它本身不提供业务层控制面和资产化抽象。

### 8.4 bb-browser

#### 更适合

- 目标网站登录复杂、反爬重、API 不开放。
- 希望 AI 直接复用“你已登录的真实浏览器状态”。
- 希望快速把网站转成 CLI/API 形式，做研究、采集、轻自动化。

#### 不太适合

- 企业后端统一认证注入场景。
- 正式检查执行主链与服务端治理。
- 高审计要求的受控执行。

#### 判断理由

- bb-browser 官方 README 的核心口号就是 “Your browser is the API”，并强调“使用你真实 Chrome 的登录态”。
- 这对复杂站点非常有效，但天然更偏用户态，而不是服务端治理态。

### 8.5 browser-use

#### 更适合

- 通用网页任务代理。
- “帮我去网页上完成这件事”的 Agent 场景。
- 需要自定义 tools、云端浏览器、stealth、profile 同步的场景。

#### 不太适合

- 强规则、强审计、强复现的企业检查主链。
- 已经有成熟资产模型，希望把检查沉淀成正式平台对象的场景。

#### 判断理由

- browser-use 官方定位是“让网站对 AI agents 可访问”，强调 Agent、Browser、Cloud、Tools、Auth profile。
- 它的强项是通用任务完成，不是资产治理。

### 8.6 Cypress

#### 更适合

- 前端团队日常 E2E 回归。
- 组件测试。
- 验证关键业务流程、联调和发布前 smoke test。

#### 不太适合

- 通用浏览器 Agent。
- 多站点自然语言驱动任务。
- 企业资产化执行平台。

#### 判断理由

- Cypress 官方明确把能力重心放在 `End-to-End` 与 `Component Testing`。
- 它非常适合测试工程，但不是通用 Agent 平台。

### 8.7 agent-browser

#### 更适合

- 给 AI agent 使用的浏览器 CLI/MCP。
- 需要 snapshot refs、HAR、network、cookies/storage、wait、batch、stream。
- 想要比纯视觉方案更省 token、更强可控性的操作层。

#### 不太适合

- 直接作为企业浏览器执行平台。
- 资产编译、权限治理、调度治理、业务对象绑定。

#### 判断理由

- agent-browser 官方定位就是“Browser automation CLI for AI agents”。
- 它更适合作为 agent 的浏览器底座，而不是平台主链。

## 9. 从 Runlet 视角看，这些项目分别像什么

### 9.1 更像竞品的项目

- `Midscene`
- `browser-use`
- `agent-browser`

原因：

- 它们都在争夺“AI 如何理解并操作界面/浏览器”这一层。

但它们与 `Runlet` 的关键差异是：

- 它们大多更偏操作层或 Agent 层。
- `Runlet` 更偏治理层与平台层。

### 9.2 更像底座的项目

- `Playwright CLI`
- `agent-browser`
- 局部场景下的 `bb-browser`

原因：

- 它们提供的是执行底座能力、会话能力、调试能力、底层浏览器操作能力。
- 这些能力可以被 `Runlet` 吸收，但不能直接替代 `Runlet` 的控制面与资产模型。

## 10. 对 Runlet 的产品路线启示

### 10.1 应该坚持自己做的能力

- `control_plane` 的统一受理与正式执行编排。
- 资产模型：`intent_aliases -> page_assets -> page_checks -> module_plans`。
- 服务端统一认证注入。
- 结果审计、artifact 管理、执行沉淀、调度晋升。
- 企业后台场景的结构化数据断言模板体系。

### 10.2 值得吸收的能力

#### 来自 `Playwright CLI`

- 更丰富的 session / state / trace / video / network / route / console 能力。
- 更完整的 agent-friendly 命令体系。

#### 来自 `agent-browser`

- snapshot refs、HAR、batch、stream、network 细粒度能力。
- 对 agent 更友好的 CLI/MCP 交互模式。

#### 来自 `Midscene`

- 更好的视觉报告、回放体验。
- 更自然的 AI 交互入口。
- 视觉辅助定位能力，作为受控 fallback 能力值得研究。

#### 来自 `bb-browser`

- 对复杂登录站点的用户态桥接思路。
- 但只能作为辅助接入思路，不宜进入正式执行主链。

### 10.3 当前不建议偏航去做的方向

- 把 `Runlet` 做成通用自由浏览器 Agent。
- 让 `runner_service` 承担开放式自然语言解释。
- 用本地浏览器登录态直接替代服务端认证注入。
- 在 V1/V2 早期把写操作、多步骤复杂业务流开放为默认主线。

## 11. 最终结论

### 11.1 如果目标是企业浏览器治理平台

`Runlet` 的路径是对的。

因为它的核心价值不在于：

- “我也能让 AI 控制网页”

而在于：

- “我能把企业检查能力收敛成可执行、可调度、可审计、可版本化的平台资产”

### 11.2 如果目标是通用浏览器 Agent

`browser-use / Midscene / agent-browser` 更接近这条路线。

### 11.3 如果目标是测试工程

`Cypress` 和 `Playwright` 体系更自然。

### 11.4 如果目标是复杂网站、真实登录态接入

`bb-browser` 的思路非常强，但不适合直接作为 `Runlet` 的正式主链。

## 12. 资料来源

### 12.1 当前仓库

- [AGENTS.md](/Users/wangpei/src/singe/Runlet/AGENTS.md)
- [后端检查执行与受控实时探测计划总结](/Users/wangpei/src/singe/Runlet/docs/summary/2026-04-03-backend-runtime-check-and-realtime-probe-summary.md)
- [AI Chat 模板化数据断言与企业 Web 仿真测试设计](/Users/wangpei/src/singe/Runlet/docs/superpowers/specs/2026-04-04-chat-template-based-data-assertion-design.md)
- [ControlPlaneService](/Users/wangpei/src/singe/Runlet/backend/src/app/domains/control_plane/service.py#L86)
- [RunnerService](/Users/wangpei/src/singe/Runlet/backend/src/app/domains/runner_service/service.py#L62)
- [Template Registry](/Users/wangpei/src/singe/Runlet/backend/src/app/domains/asset_compiler/template_registry.py)

### 12.2 外部公开资料

- [Midscene GitHub](https://github.com/web-infra-dev/midscene)
- [Midscene 官方网站](https://midscenejs.com/)
- [Playwright CLI 官方文档](https://playwright.dev/docs/getting-started-cli)
- [Playwright Test CLI](https://playwright.dev/docs/test-cli)
- [bb-browser 官方 README](https://raw.githubusercontent.com/epiral/bb-browser/main/README.md)
- [bb-browser release 摘要](https://newreleases.io/project/github/epiral/bb-browser/release/v0.8.0)
- [browser-use GitHub](https://github.com/browser-use/browser-use)
- [browser-use 官方网站](https://browser-use.com)
- [Cypress Testing Types](https://docs.cypress.io/app/core-concepts/testing-types)
- [agent-browser GitHub](https://github.com/vercel-labs/agent-browser)

### 12.3 说明

- 除 `Runlet` 外，外部项目的星级评价属于基于公开资料的工程判断，不代表官方自评。
- `bb-browser` 的公开资料主要基于其官方 README 与 release 摘要；相较 Playwright、Cypress、Midscene，公开工程细节可验证度略低，因此相关判断置信度略低一档。
