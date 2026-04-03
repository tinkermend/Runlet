# Runlet vs bb-browser 效率对比与致命性问题分析

## 一、效率对比分析

### 1. 执行路径效率

| 指标 | Runlet | bb-browser | 差距分析 |
|------|--------|------------|----------|
| **单次执行延迟** | 高（100-500ms 队列 + 调度开销） | 极低（直接 CDP 调用） | Runlet 慢 10-50 倍 |
| **浏览器启动** | 每次 job 新建 browser/context | 复用已打开的 Chrome | Runlet 多 2-5s 冷启动 |
| **并发能力** | 依赖 worker 进程数 | 依赖 Chrome 标签页数 | Runlet 扩展成本高 |
| **端到端延迟** | 3-10s（含队列等待） | <1s | 数量级差距 |

### 2. 资源消耗对比

**Runlet 的资源模型：**
```python
# 每次执行都要经历：
PlaywrightRunnerRuntime()
  ├── async_playwright().start()      # ~500ms
  ├── browser.launch(headless=True)   # ~1-2s
  ├── context.new_context()           # ~200ms
  ├── page.goto() + wait_until        # ~1-3s
  └── 执行检查
  └── close()                         # ~200ms
```

**bb-browser 的资源模型：**
```
已运行的 Chrome
  └── CDP WebSocket 直接通信        # ~50ms
  └── eval / fetch 执行             # ~100-500ms
```

### 3. 架构效率瓶颈

| 瓶颈点 | 代码位置 | 影响 |
|--------|----------|------|
| **浏览器生命周期管理** | `playwright_runtime.py:33-35` | 每次执行新建 browser，无连接池 |
| **数据库同步等待** | `crawler_service.py:684-688` | 每页采集后 `_flush()`，IO 密集型 |
| **队列轮询** | `runner.py:76-86` | `poll_interval_ms` 固定间隔，延迟与 CPU 消耗权衡 |
| **单 worker 单 session** | `runner.py:154-185` | 无并发执行能力 |

---

## 二、当前方案的致命性问题

### 致命问题 1：浏览器连接无池化

**问题代码：**
```python
# playwright_runtime.py:32-35
self._playwright = await async_playwright().start()
self._browser = await self._playwright.chromium.launch(headless=True)  # 每次都新建
self._context = await self._browser.new_context(storage_state=storage_state)
```

**影响：**
- 每次检查都要经历 2-5s 的浏览器启动
- 无法支撑高频定时检查（如每分钟检查）
- 资源浪费严重（启动/关闭开销占 80% 执行时间）

**企业级要求：**
- 需要浏览器连接池（类似数据库连接池）
- 支持 context 复用和隔离
- 支持并发标签页执行

---

### 致命问题 2：Worker 单线程模型

**问题代码：**
```python
# runner.py:71-86
async def run_forever(self, ...):
    while True:
        handled = await self.run_once()  # 一次只处理一个 job
        if not handled:
            await anyio.sleep(interval_seconds)  # 固定轮询间隔
```

**影响：**
- 一个 worker 进程同时只能执行一个检查
- 要提升并发必须启动多个 worker 进程
- 进程间资源隔离导致浏览器无法共享

**企业级要求：**
- Worker 内部需要并发执行能力
- 或者使用异步任务队列（Celery / RQ）
- 支持优先级调度和资源配额

---

### 致命问题 3：数据库 flush 过于频繁

**问题代码：**
```python
# crawler_service.py:661, 684, 687
await self._flush()  # 每页、每菜单、每元素都 flush
```

**影响：**
- 一次采集产生数十次数据库往返
- 事务边界过细，无法批量优化
- 高并发时数据库成为瓶颈

**企业级要求：**
- 批量写入（bulk insert）
- 合理的事务边界（按 snapshot 批量提交）
- 异步写入或队列缓冲

---

### 致命问题 4：缺乏浏览器状态预热

**当前流程：**
```
收到检查请求 -> 启动浏览器 -> 注入认证 -> 执行检查 -> 关闭浏览器
```

**企业级要求：**
```
认证刷新任务 -> 预热浏览器 + 注入认证 -> 保持 warm 状态
检查请求 -> 复用 warm browser -> 直接执行 -> 归还连接池
```

---

### 致命问题 5：漂移检测与执行耦合

**当前设计：**
- 漂移检测依赖 `asset_compiler` 重新编译
- 执行时无法实时感知页面变化
- 失败后才知道资产过期

**企业级要求：**
- 执行前快速指纹校验（毫秒级）
- 实时探测与预编译资产混合策略
- 优雅降级（资产失效时自动 fallback 到实时探测）

---

### 致命问题 6：缺乏执行隔离和熔断

**当前缺失：**
- 无页面级超时控制（只有 `time_budget_ms` 传入但未严格使用）
- 无失败重试策略
- 无资源使用上限（CPU/内存/网络）

**企业级要求：**
- 严格的 sandbox 隔离
- 熔断机制（连续失败时暂停检查）
- 资源配额和 OOM 保护

---

## 三、效率优化建议（按优先级）

### P0：浏览器连接池
```python
class BrowserPool:
    """管理预热好的浏览器上下文"""
    async def acquire(self, system_id: UUID) -> PooledContext:
        """获取已注入认证的上下文"""
        
    async def release(self, context: PooledContext):
        """归还上下文，不清除状态"""
```

### P1：批量数据库操作
```python
# 替代逐条 flush
async def bulk_persist_elements(self, elements: list[ElementCandidate]):
    await self.session.bulk_save_objects(elements)
    await self._commit()  # 一次提交
```

### P2：异步任务队列
- 评估从 SQLQueue 迁移到 Redis/RabbitMQ
- 支持优先级、延迟执行、死信队列

### P3：执行引擎优化
- 分离"计划解析"和"执行"阶段
- 支持 module_plan 的本地缓存
- 预编译 Playwright 脚本避免运行时生成

---

## 四、与 bb-browser 的效率差距总结

| 场景 | Runlet 预估 | bb-browser 预估 | 差距 |
|------|-------------|-----------------|------|
| 单次页面检查 | 5-10s | 0.5-1s | **10x** |
| 100 个定时检查 | 需要 10+ workers | 单 Chrome 实例 | **资源 10x** |
| 高频检查 (1min) | 不可行 | 可行 | **可用性** |
| 并发扩展 | 线性增加 workers | 增加标签页 | **成本 5x** |

---

## 五、核心结论

当前 Runlet 架构适合**低频、重治理**的企业场景，但无法支撑**高频、大规模**的自动化测试需求。如果要对标 bb-browser 的效率，需要：

1. **立即**：实现浏览器连接池（P0）
2. **短期**：优化数据库批量写入（P1）
3. **中期**：迁移到专业任务队列（P2）

否则在真实企业环境中，定时检查功能将因性能问题而无法落地。

---

*分析日期：2026-04-03*
