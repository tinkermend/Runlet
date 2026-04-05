# `asset_compile` 与 `crawl` 同池运行方案分析

## 背景

当前项目希望在**不做大改动**的前提下，提高 `crawl` 与 `run_check` 两类任务的排队效率与执行稳定性。围绕执行池划分，存在一个具体问题：

- `asset_compile` 应该跟 `run_check` 一池
- 还是跟 `crawl` 一池
- 或者独立成第三类后台池

本文只整理当前阶段的判断结论，不涉及具体实施方案落地。

---

## 结论

当前阶段，`asset_compile` 更适合**跟 `crawl` 一池运行**，更准确地说，应视为“采集后处理池”的组成部分，而不应与 `run_check` 共用正式检查执行池。

---

## 主要理由

### 1. 当前链路上，`asset_compile` 本来就是 `crawl` 的后继步骤

从现有代码看，`crawl` 成功后会直接追加 `asset_compile` 作业：

- [crawl_job.py](/Users/wangpei/src/singe/Runlet/backend/src/app/jobs/crawl_job.py)

也就是说，在运行时语义上，`asset_compile` 不是独立前台业务流，而是：

```text
crawl -> snapshot -> asset_compile -> reconciliation cascade
```

它天然属于采集后的资产生成与收敛阶段。

### 2. `asset_compile` 的输入完全依赖 `crawl` 产物

`asset_compile` 任务的核心输入是 `snapshot_id`：

- [asset_compile_job.py](/Users/wangpei/src/singe/Runlet/backend/src/app/jobs/asset_compile_job.py)

而 `snapshot_id` 只会由采集成功后产生，因此 `asset_compile` 本质上是在消费采集事实层结果，而不是在消费正式检查链路的执行上下文。

### 3. `asset_compile` 的资源特征更接近后台任务，而不是低延迟检查

从编译服务看，`asset_compile` 会进行大量后台型处理：

- 读取 `pages / menu_nodes / page_elements`
- 计算页面指纹与漂移状态
- 生成 `page_assets / page_checks / module_plans`
- 执行 reconciliation decision 与审计记录

相关代码见：

- [asset_compiler/service.py](/Users/wangpei/src/singe/Runlet/backend/src/app/domains/asset_compiler/service.py)

这类任务的典型特征是：

- 数据库读写重
- 批量对象多
- 对响应时延不敏感
- 更适合后台吞吐治理

这与 `run_check` 追求低排队时延、低尾延迟的目标并不一致。

### 4. 如果把 `asset_compile` 放进 `run_check` 池，会污染正式检查时延

`run_check` 的目标是尽快消费现成的 `page_check / module_plan` 并执行受控检查：

- [run_check_job.py](/Users/wangpei/src/singe/Runlet/backend/src/app/jobs/run_check_job.py)

如果 `asset_compile` 和 `run_check` 混在同一执行池中，会出现下面的问题：

- 编译任务的大量数据库操作会挤占检查任务的 worker 时间
- 采集后的批量编译会把正式检查排队时间拉长
- 检查链路的低延迟目标会被后台资产生成链路污染

因此，把 `asset_compile` 放到正式检查池中，不符合当前“检查优先”的性能优化目标。

---

## 与其他两种方案的比较

### 方案 A：`asset_compile` 跟 `run_check` 一池

不推荐。

原因：

- 编译属于后台资产生成，不属于前台检查执行
- 会直接污染 `run_check` 的排队与尾延迟
- 与“检查优先、采集后置”的容量治理目标冲突

### 方案 B：`asset_compile` 跟 `crawl` 一池

当前阶段最合适。

原因：

- 语义上属于 `crawl` 后处理
- 输入输出都依赖采集链
- 便于把“采集及其后处理”整体隔离到后台池
- 可以与 `run_check + auth_refresh` 池形成稳定边界

### 方案 C：`asset_compile` 单独第三池

当前阶段不必优先。

原因：

- 虽然隔离更细，但对当前“小改动提性能”的目标来说偏重
- 现在首要矛盾是检查池不要被后台任务污染，而不是后台链路再继续细拆
- 在没有明显证据表明 `asset_compile` 自己已经成为单独瓶颈前，不值得优先引入第三池复杂度

---

## 当前阶段建议

如果项目当前目标是：

- 不做大改动
- 提升 `crawl` 与 `run_check` 的性能
- 降低正式检查的排队时延

那么更合理的执行池划分是：

```text
check worker:
  - run_check
  - auth_refresh

crawl worker:
  - crawl
  - asset_compile
```

这里的关键不是简单把 `asset_compile` 归到 `crawl`，而是把它归入**采集后处理链**，避免与正式检查执行池争用同一类 worker 容量。

---

## 后续再升级为第三池的信号

当前不建议优先把 `asset_compile` 单独拆池，但如果后续出现下面信号，再考虑升级：

- `asset_compile` 耗时明显高于 `crawl`，开始反过来堵塞采集吞吐
- 采集与编译的扩容策略已经明显不同
- 资产编译的数据库负载、审计负载、漂移决策负载成为独立瓶颈
- 需要单独治理“采集速度”和“资产生成速度”

在这些信号出现之前，`crawl + asset_compile` 作为同一后台执行池，通常是更符合当前项目阶段的选择。

---

## 总结

当前项目下，`asset_compile` 不应被视为与 `run_check` 同级的前台任务，而应被视为 `crawl` 成功后的后台后处理阶段。

因此，现阶段最合理的判断是：

**`asset_compile` 跟 `crawl` 一池运行，而不是跟 `run_check` 一池，也暂时不必升级为第三类独立执行池。**
