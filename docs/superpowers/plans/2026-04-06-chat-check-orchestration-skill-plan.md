# Chat Check Orchestration Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仓库内新增一个项目级“检查编排 skill”包，统一覆盖普通页面检查与模板化只读检查的对话编排、PAT 前置校验、候选推荐、正式执行结果转述与成功后可选发布流程。

**Architecture:** 该实现只落在 `skills/` 编排层，不改 `control_plane -> asset_compiler -> runner_service` 的正式执行真相。主 `SKILL.md` 只负责状态机、门控与对话规则，接口契约、模板槽位、结果格式和认证前置拆到 `references/`，并补齐 `agents/openai.yaml` 与仓库级变更记录。验证以“内容断言 + 手工压力场景”结合，不引入新的后端能力。

**Tech Stack:** Markdown, YAML, Codex Skill conventions, shell verification (`rg`, `test`, `git diff`)

---

## 实施约束

- 全流程遵循 `@test-driven-development` 的精神：先写失败校验，再写最小内容使其通过。
- 编写 skill 时同时参考 `@writing-skills` 与 `@skill-creator`，保持 skill 主文件简洁，把细节拆进 `references/`。
- 不修改后端正式执行逻辑，不把 `realtime_probe` 作为默认 skill 主链。
- 所有 skill 侧 `/api/v1/check-requests*` 调用说明一律按“统一携带 `RUNLET_PAT`”编写，不依赖当前未完全收口的鉴权空洞。
- 每个任务结束后都做可见验证；文档变更同步更新 `CHANGELOG.md`。

## File Structure

**Files to Create:**

- `skills/chat-check-orchestrator/SKILL.md`
  - skill 主流程：触发条件、非目标、状态机、补问门控、执行顺序、退出条件。
- `skills/chat-check-orchestrator/references/setup-and-auth.md`
  - `RUNLET_PAT` / `RUNLET_BASE_URL` 前置要求与缺失时的终止规则。
- `skills/chat-check-orchestrator/references/api-contract.md`
  - `check-requests*` 五类接口的最小调用契约。
- `skills/chat-check-orchestrator/references/decision-rules.md`
  - 补问、推荐、直执行、停止条件的明确规则。
- `skills/chat-check-orchestrator/references/template-slots.md`
  - V1 模板槽位定义、必填项与自然语言示例。
- `skills/chat-check-orchestrator/references/result-format.md`
  - 结果转述模板与输出约束。
- `skills/chat-check-orchestrator/agents/openai.yaml`
  - skill UI 元数据。

**Files to Modify:**

- `CHANGELOG.md`
  - 记录本次 skill 实现与验证结果。

---

### Task 1: 搭建 Skill 包骨架

**Files:**
- Create: `skills/chat-check-orchestrator/SKILL.md`
- Create: `skills/chat-check-orchestrator/references/setup-and-auth.md`
- Create: `skills/chat-check-orchestrator/references/api-contract.md`
- Create: `skills/chat-check-orchestrator/references/decision-rules.md`
- Create: `skills/chat-check-orchestrator/references/template-slots.md`
- Create: `skills/chat-check-orchestrator/references/result-format.md`
- Create: `skills/chat-check-orchestrator/agents/openai.yaml`

- [ ] **Step 1: 先写失败校验（目标 skill 包尚不存在）**

```bash
cd /Users/wangpei/src/singe/Runlet
test -f skills/chat-check-orchestrator/SKILL.md
```

- [ ] **Step 2: 运行校验确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && test -f skills/chat-check-orchestrator/SKILL.md`
Expected: 非零退出码，说明 skill 包还不存在。

- [ ] **Step 3: 最小创建目录与占位文件**

```text
skills/chat-check-orchestrator/
├── SKILL.md
├── references/
│   ├── setup-and-auth.md
│   ├── api-contract.md
│   ├── decision-rules.md
│   ├── template-slots.md
│   └── result-format.md
└── agents/
    └── openai.yaml
```

- [ ] **Step 4: 运行存在性校验确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && test -f skills/chat-check-orchestrator/SKILL.md && test -f skills/chat-check-orchestrator/references/setup-and-auth.md && test -f skills/chat-check-orchestrator/agents/openai.yaml`
Expected: 退出码为 0。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add skills/chat-check-orchestrator
git commit -m "feat: scaffold chat check orchestrator skill package"
```

---

### Task 2: 编写主 `SKILL.md` 的状态机与边界

**Files:**
- Modify: `skills/chat-check-orchestrator/SKILL.md`

- [ ] **Step 1: 先写失败校验（主 skill 还未包含核心状态机和边界）**

```bash
cd /Users/wangpei/src/singe/Runlet
rg -n "PreflightAuth|AskOneQuestion|OfferPublish|realtime_probe|RUNLET_PAT" skills/chat-check-orchestrator/SKILL.md
```

- [ ] **Step 2: 运行校验确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "PreflightAuth|AskOneQuestion|OfferPublish|realtime_probe|RUNLET_PAT" skills/chat-check-orchestrator/SKILL.md`
Expected: 非零退出码或命中不完整，说明主流程还没写好。

- [ ] **Step 3: 最小实现主 skill 内容**

```md
---
name: chat-check-orchestrator
description: Use when a user wants to run a Runlet page check or readonly template check from chat and needs slot filling, candidate selection, execution, result summarization, or optional publish-after-success flow
---

# Chat Check Orchestrator

## Overview

- 这是一个检查型对话编排 skill，不是正式执行器。
- 正式执行真相仍然是 `control_plane -> asset_compiler -> runner_service`。

## Core Flow

1. `PreflightAuth`
2. `ParseIntent`
3. `AssessReadiness`
4. `AskOneQuestion | Recommend | Execute`
5. `PollStatus`
6. `FetchResult`
7. `SummarizeResult`
8. `OfferPublish`
```

- [ ] **Step 4: 运行内容校验确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "PreflightAuth|ParseIntent|AssessReadiness|AskOneQuestion|Recommend|Execute|PollStatus|FetchResult|SummarizeResult|OfferPublish|RUNLET_PAT|realtime_probe" skills/chat-check-orchestrator/SKILL.md`
Expected: 命中完整状态与关键边界说明。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add skills/chat-check-orchestrator/SKILL.md
git commit -m "feat: define chat check orchestrator main workflow"
```

---

### Task 3: 编写认证前置与 API 契约 references

**Files:**
- Modify: `skills/chat-check-orchestrator/references/setup-and-auth.md`
- Modify: `skills/chat-check-orchestrator/references/api-contract.md`

- [ ] **Step 1: 先写失败校验（尚未明确 PAT 前置与五类接口）**

```bash
cd /Users/wangpei/src/singe/Runlet
rg -n "RUNLET_PAT|RUNLET_BASE_URL|缺失时立即停止|Web 管理台创建 PAT" skills/chat-check-orchestrator/references/setup-and-auth.md
rg -n "check-requests:candidates|POST /api/v1/check-requests|GET /api/v1/check-requests/\\{request_id\\}|/result|:publish" skills/chat-check-orchestrator/references/api-contract.md
```

- [ ] **Step 2: 运行校验确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "RUNLET_PAT|RUNLET_BASE_URL|缺失时立即停止|Web 管理台创建 PAT" skills/chat-check-orchestrator/references/setup-and-auth.md && rg -n "check-requests:candidates|POST /api/v1/check-requests|GET /api/v1/check-requests/\\{request_id\\}|/result|:publish" skills/chat-check-orchestrator/references/api-contract.md`
Expected: 至少一条命令失败，说明引用文档尚未成型。

- [ ] **Step 3: 最小实现认证与 API 契约**

```md
# Setup And Auth

- 必须先检查 `RUNLET_PAT`
- 可选读取 `RUNLET_BASE_URL`
- 若 `RUNLET_PAT` 缺失，直接终止并提示去 Web 管理台创建 3/7 天 PAT
- 所有 `/api/v1/check-requests*` 调用统一带 `Authorization: Bearer ${RUNLET_PAT}`
```

```md
# API Contract

- `POST /api/v1/check-requests:candidates`
- `POST /api/v1/check-requests`
- `GET /api/v1/check-requests/{request_id}`
- `GET /api/v1/check-requests/{request_id}/result`
- `POST /api/v1/check-requests/{request_id}:publish`
```

- [ ] **Step 4: 运行校验确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "RUNLET_PAT|RUNLET_BASE_URL|缺失时立即停止|Web 管理台创建 PAT" skills/chat-check-orchestrator/references/setup-and-auth.md && rg -n "check-requests:candidates|POST /api/v1/check-requests|GET /api/v1/check-requests/\\{request_id\\}|/result|:publish" skills/chat-check-orchestrator/references/api-contract.md`
Expected: 命中 PAT 前置规则与五类接口说明。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add skills/chat-check-orchestrator/references/setup-and-auth.md skills/chat-check-orchestrator/references/api-contract.md
git commit -m "feat: document auth preflight and api contract for check skill"
```

---

### Task 4: 编写决策规则、模板槽位与结果格式 references

**Files:**
- Modify: `skills/chat-check-orchestrator/references/decision-rules.md`
- Modify: `skills/chat-check-orchestrator/references/template-slots.md`
- Modify: `skills/chat-check-orchestrator/references/result-format.md`

- [ ] **Step 1: 先写失败校验（尚未补齐门控、模板和结果规范）**

```bash
cd /Users/wangpei/src/singe/Runlet
rg -n "补问|推荐|直执行|候选为空|分数接近" skills/chat-check-orchestrator/references/decision-rules.md
rg -n "has_data|no_data|field_equals_exists|status_exists|count_gte" skills/chat-check-orchestrator/references/template-slots.md
rg -n "结论|定位|证据|后续动作|needs_recrawl|needs_recompile" skills/chat-check-orchestrator/references/result-format.md
```

- [ ] **Step 2: 运行校验确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "补问|推荐|直执行|候选为空|分数接近" skills/chat-check-orchestrator/references/decision-rules.md && rg -n "has_data|no_data|field_equals_exists|status_exists|count_gte" skills/chat-check-orchestrator/references/template-slots.md && rg -n "结论|定位|证据|后续动作|needs_recrawl|needs_recompile" skills/chat-check-orchestrator/references/result-format.md`
Expected: 至少一条命令失败，说明关键规则还未写全。

- [ ] **Step 3: 最小实现三份 reference**

```md
# Decision Rules

- 信息缺失时补问，不做推荐
- 信息足够但多候选时推荐，不偷跑执行
- 仅在高置信稳定第一名时允许直执行
- 候选为空或候选接近时必须停下确认
```

```md
# Template Slots

| template_code | required_slots |
| --- | --- |
| has_data | none |
| no_data | none |
| field_equals_exists | field, value |
| status_exists | status |
| count_gte | threshold |
```

```md
# Result Format

1. 结论
2. 定位
3. 证据
4. 后续动作
```

- [ ] **Step 4: 运行校验确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "补问|推荐|直执行|候选为空|分数接近" skills/chat-check-orchestrator/references/decision-rules.md && rg -n "has_data|no_data|field_equals_exists|status_exists|count_gte" skills/chat-check-orchestrator/references/template-slots.md && rg -n "结论|定位|证据|后续动作|needs_recrawl|needs_recompile" skills/chat-check-orchestrator/references/result-format.md`
Expected: 三份文件都命中对应规则。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add skills/chat-check-orchestrator/references/decision-rules.md skills/chat-check-orchestrator/references/template-slots.md skills/chat-check-orchestrator/references/result-format.md
git commit -m "feat: add decision, template, and result references for check skill"
```

---

### Task 5: 补齐 `agents/openai.yaml` 与仓库级变更记录

**Files:**
- Modify: `skills/chat-check-orchestrator/agents/openai.yaml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 先写失败校验（缺少 UI 元数据与 changelog 记录）**

```bash
cd /Users/wangpei/src/singe/Runlet
rg -n "display_name|short_description|default_prompt" skills/chat-check-orchestrator/agents/openai.yaml
rg -n "chat-check-orchestrator|检查编排 skill" CHANGELOG.md
```

- [ ] **Step 2: 运行校验确认失败**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "display_name|short_description|default_prompt" skills/chat-check-orchestrator/agents/openai.yaml && rg -n "chat-check-orchestrator|检查编排 skill" CHANGELOG.md`
Expected: 至少一条命令失败，说明元数据或变更记录尚未补齐。

- [ ] **Step 3: 最小实现 UI 元数据与 changelog**

```yaml
display_name: Chat Check Orchestrator
short_description: Run Runlet page checks from chat with slot filling and candidate gating
default_prompt: Use this skill when the user wants to run a Runlet page check or readonly template check from chat.
```

```md
- 新增项目级 skill `skills/chat-check-orchestrator/`，统一沉淀 PAT 前置校验、候选推荐门控、检查执行与结果格式化规则。
```

- [ ] **Step 4: 运行校验确认通过**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "display_name|short_description|default_prompt" skills/chat-check-orchestrator/agents/openai.yaml && rg -n "chat-check-orchestrator|检查编排 skill" CHANGELOG.md`
Expected: 命中 skill 元数据与 changelog 记录。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add skills/chat-check-orchestrator/agents/openai.yaml CHANGELOG.md
git commit -m "feat: register chat check orchestrator skill metadata"
```

---

### Task 6: 按压力场景验证 Skill 可执行性

**Files:**
- Modify: `skills/chat-check-orchestrator/SKILL.md`
- Modify: `skills/chat-check-orchestrator/references/setup-and-auth.md`
- Modify: `skills/chat-check-orchestrator/references/api-contract.md`
- Modify: `skills/chat-check-orchestrator/references/decision-rules.md`
- Modify: `skills/chat-check-orchestrator/references/template-slots.md`
- Modify: `skills/chat-check-orchestrator/references/result-format.md`

- [ ] **Step 1: 先定义失败标准（以下任一场景回答错误即视为失败）**

```text
1. “帮我看一下 ERP” -> 必须补问检查目标
2. “看看 ERP 用户管理页有没有 alice” -> 走模板检查候选或补模板槽位
3. “检查 ERP 首页菜单是否完整” -> 走普通检查，不强套模板
4. “帮我检查库存页并且以后每天跑” -> 先检查，成功后再询问是否发布
5. 未配置 RUNLET_PAT -> 立即终止，不进入候选和执行
6. 候选分数接近 -> 展示推荐，不允许直执行
```

- [ ] **Step 2: 手工运行压力验证**

Run:
1. 在当前仓库上下文开启一个新的 skill 对话。
2. 依次输入本任务 Step 1 的 6 条 prompt。
3. 对照 `skills/chat-check-orchestrator/SKILL.md` 与各 `references/*.md` 检查回答是否落到预期分支。
Expected: 六个场景都能稳定落到正确分支。

- [ ] **Step 3: 如有偏差，仅做最小修正**

```text
- 若多问了两个问题，收紧 `AskOneQuestion` 规则
- 若误触发直执行，收紧 `decision-rules.md`
- 若结果转述过度展开 JSON，收紧 `result-format.md`
```

- [ ] **Step 4: 运行最终静态校验**

Run: `cd /Users/wangpei/src/singe/Runlet && rg -n "PreflightAuth|AskOneQuestion|OfferPublish" skills/chat-check-orchestrator/SKILL.md && rg -n "RUNLET_PAT|Authorization: Bearer" skills/chat-check-orchestrator/references/setup-and-auth.md skills/chat-check-orchestrator/references/api-contract.md && rg -n "has_data|no_data|field_equals_exists|status_exists|count_gte" skills/chat-check-orchestrator/references/template-slots.md`
Expected: 关键状态、PAT 前置和模板槽位全部命中。

- [ ] **Step 5: 提交**

```bash
cd /Users/wangpei/src/singe/Runlet
git add skills/chat-check-orchestrator
git commit -m "feat: finalize chat check orchestrator skill validation"
```

---

## 完成定义

满足以下条件才算完成：

1. `skills/chat-check-orchestrator/` 目录完整存在。
2. 主 `SKILL.md` 已明确状态机、边界、补问规则、直执行门控和发布后置流程。
3. `references/` 已覆盖认证前置、API 契约、决策规则、模板槽位和结果格式。
4. `agents/openai.yaml` 已存在并与 skill 内容一致。
5. `CHANGELOG.md` 已记录本次 skill 落地。
6. 六个压力场景验证通过，没有出现越权执行、缺 PAT 仍继续、或把发布提前进主链的问题。
