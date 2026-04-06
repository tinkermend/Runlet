---
name: chat-check-orchestrator
description: Use when a user wants to run a Runlet page check or readonly template check from chat and needs slot filling, candidate selection, execution, result summarization, or optional publish-after-success flow
---

# Chat Check Orchestrator

## 概览

- 这是一个检查型对话编排 skill，不是正式执行器。
- 正式执行真相仍是 `control_plane -> asset_compiler -> runner_service`。
- 该 skill 负责对话槽位收集、候选门控、执行触发与结果总结，不负责后端认证注入。

## 触发条件

- 用户希望在聊天中发起 Runlet 页面检查。
- 用户希望发起只读模板检查并获得结果摘要。
- 用户需要“补问一个关键参数 / 候选推荐 / 直接执行 / 结果总结 / 成功后可选发布”这一整套编排。

## 非目标与边界

- 不绕过 `control_plane` 直接执行。
- 不把自由脚本文本作为正式执行真相。
- 不负责服务端认证注入策略。
- `realtime_probe` 不是默认路径，仅在后续专门策略中才可考虑。
- 发布不是主链步骤，仅在本次执行成功后进入可选询问。

## 前置校验

- 必须先检查 `RUNLET_PAT`。
- 缺少 `RUNLET_PAT` 时立即停止，并提示用户先在管理台创建 PAT。
- `RUNLET_BASE_URL` 可选，未设置时使用约定默认地址。

## 核心流程（状态机）

1. `PreflightAuth`
2. `ParseIntent`
3. `AssessReadiness`
4. `AskOneQuestion | Recommend | Execute`
5. `PollStatus`
6. `FetchResult`
7. `SummarizeResult`
8. `OfferPublish`

## 意图解析（ParseIntent）

- 仅当用户明确表达结构化只读断言（字段值是否存在、状态是否存在、数量是否不少于阈值等）时，才进入“模板化只读检查”路径并按 `template-slots.md` 补槽位。
- 若用户表达接近模板断言、但还不足以确定具体断言类型或关键槽位（例如“有没有数据/有没有状态/大概有多少条”），先走 `AskOneQuestion` 澄清，不要直接在模板检查与普通页面检查之间自行选边。
- 对“菜单是否完整/是否缺项/页面结构是否齐全”等结构完整性诉求，优先走普通页面检查，不要强套 `has_data/no_data/count_gte` 等模板。

## 状态门控说明

- `AssessReadiness` 判定分支：
  - 信息不足或候选为空 -> `AskOneQuestion`（单轮只问一个关键问题；若澄清后仍无法形成候选则停止）
  - 未达高置信直执行门槛且存在可确认候选 -> `Recommend`（给出候选或要求用户确认目标对象；包含多候选、候选分数接近、单候选但信号不足等情况）
  - `Recommend` 后，只有在用户明确确认目标对象/候选后才允许进入 `Execute`
  - 满足高置信直执行门槛 -> `Execute`
- `OfferPublish` 仅在执行成功后出现；失败或未完成时不进入发布分支。

## 参考入口

- `references/setup-and-auth.md`：环境变量与 PAT 前置校验入口。
- `references/api-contract.md`：`check-requests*` 调用契约与字段入口。
- `references/decision-rules.md`：补问、推荐与直执行门控规则入口。
- `references/template-slots.md`：模板化检查槽位与参数约束入口。
- `references/result-format.md`：执行结果摘要与证据输出格式入口。

## 完成与退出条件

- 缺少 `RUNLET_PAT`：立即停止并提示先创建 PAT。
- 澄清后仍信息不足：停止本轮并要求用户补充后再试。
- 用户拒绝候选推荐：停止本轮，不强制执行。
- 执行成功：输出结果摘要，并可选询问是否发布。
- 执行失败或超时：输出失败摘要后结束本轮。
- 若失败证据指向登录页回退或认证态失效（例如最终 URL/标题落到登录页，且 `auth_status` 为 `reused` 后导航失败），后续动作优先提示“先去控制台刷新认证，再重试检查”，不要只给泛化失败结论。
