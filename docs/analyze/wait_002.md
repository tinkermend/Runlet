# Runlet 企业 AI 自动化测试场景下的其他致命短板分析

## 背景

本文档分析除浏览器池化、Worker 串行、数据库批量写入之外，当前项目在企业 AI 自动化测试场景下的其他致命短板。

---

## 致命短板 4：检查类型过于简单

### 当前支持的检查类型

```python
# check_templates.py:6-38
checks = [
    StandardCheckDefinition(check_code="page_open", goal="page_open", ...),
    # 可选：table_render（如果有 table）
    # 可选：open_create_modal（如果有创建按钮）
]
```

### 问题

- 只有 3 种标准检查：`page_open`、`table_render`、`open_create_modal`
- 无法覆盖企业真实场景：
  - 表单验证（必填项、格式校验）
  - 数据一致性（列表数据 vs 详情页）
  - 业务流程（创建 → 编辑 → 删除）
  - API 响应检查
  - 性能指标（加载时间、接口延迟）

### 企业级要求

- 可扩展的检查模板系统
- 支持自定义检查逻辑（代码注入）
- 支持数据驱动测试（参数化）

---

## 致命短板 5：元素定位策略脆弱

### 当前定位生成逻辑

```python
# dom_menu.py:146-162
def _build_locator(self, *, role, text, aria_label, fallback_tag):
    if role and text:
        return f"role={role}[name='{self._escape_quote(text)}']"
    if text:
        return f"text='{self._escape_quote(text)}']"
    return f"css={fallback_tag}"  # 最后的 fallback 非常脆弱
```

### 问题

- 依赖 `role` 和 `text`，但现代前端框架（React/Vue）经常动态生成这些
- 没有多重定位策略 fallback
- 没有元素稳定性评分机制（`stability_score` 固定 0.7）
- 没有处理动态 ID、随机 class

### 企业级要求

- 多重定位策略（role → data-testid → css → xpath）
- 元素指纹（多属性组合）
- 智能等待（不仅是固定 timeout）

---

## 致命短板 6：缺乏数据断言能力

### 当前执行模型

```python
# module_executor.py:40-166
# 只能执行预定义模块：auth.inject_state → nav.menu_chain → assert.table_visible
```

### 问题

- 无法断言具体数据（如"表格第一行显示'张三'"）
- 无法跨页面数据关联
- 无法处理异步数据加载
- 没有数据提取和存储机制

### 企业级要求

- 数据提取（从页面提取结构化数据）
- 数据断言（等于、包含、正则匹配）
- 数据关联（从 A 页面提取 ID，在 B 页面使用）

---

## 致命短板 7：失败恢复和重试机制缺失

### 当前失败处理

```python
# module_executor.py:146-160
except Exception as exc:
    step_results.append(StepExecutionResult(
        module=module,
        status=RunnerRunStatus.FAILED,
        detail=str(exc),
        output={"failure_category": failure_category.value},
    ))
    return ModuleExecutionResult(status=RunnerRunStatus.FAILED, ...)
```

### 问题

- 任何步骤失败立即终止
- 没有重试机制（网络抖动、元素未就绪）
- 没有优雅降级（主路径失败时尝试备选路径）
- 没有失败分类后的自动恢复策略

### 企业级要求

- 步骤级重试（指数退避）
- 失败分类后的不同策略：
  - `PAGE_NOT_READY` → 等待后重试
  - `AUTH_BLOCKED` → 触发认证刷新
  - `ASSERTION_FAILED` → 立即失败

---

## 致命短板 8：缺乏测试数据管理

### 当前状态

- 没有测试数据概念
- 每次检查使用相同路径（如 `/users`）
- 无法处理需要特定前置数据的场景

### 企业级要求

- 测试数据创建/清理机制
- 数据隔离（不同检查使用不同数据集）
- 数据模板和 faker 支持

---

## 致命短板 9：无并发控制和资源隔离

### 当前 Worker 模型

```python
# runner.py:71-86
async def run_forever(self, ...):
    while True:
        handled = await self.run_once()  # 一次一个
        await anyio.sleep(interval_seconds)
```

### 问题

- 单 Worker 单执行
- 没有资源配额（一个检查可能占用所有资源）
- 没有优先级队列
- 没有并发限制（可能同时启动 100 个浏览器）

### 企业级要求

- 并发控制（最大并行数）
- 资源配额（CPU/内存/超时）
- 优先级队列（紧急检查优先）
- 隔离（不同系统资源独立）

---

## 致命短板 10：缺乏可视化调试能力

### 当前产物

- 截图（`capture_screenshot`）
- 执行日志（`step_results`）

### 缺失

- 执行过程录屏
- 网络请求/响应记录
- 控制台日志捕获
- 元素高亮（失败时标记元素）
- 可视化回放

### 企业级要求

- Playwright trace 集成
- 视频录制
- HAR 文件导出
- 可视化报告（不是 JSON）

---

## 致命短板 11：环境管理缺失

### 当前设计

- 一个 `System` 对应一个 `base_url`
- 没有环境概念（dev/staging/prod）

### 企业级要求

- 多环境支持（同一系统不同环境）
- 环境级配置（认证、超时）
- 跨环境资产复用（检查逻辑相同，环境不同）

---

## 致命短板 12：集成和扩展能力弱

### 当前集成

- MCP server（只读查询）
- CLI（简单命令）

### 缺失

- Webhook（检查结果通知）
- CI/CD 集成（Jenkins/GitHub Actions）
- 插件系统（自定义模块）
- API 限流和认证

---

## 致命短板优先级矩阵

| 短板 | 阻塞高频使用 | 阻塞企业落地 | 短期可修复 |
|------|-------------|-------------|-----------|
| 浏览器池化 | ✅ | ✅ | ✅ |
| Worker 并发 | ✅ | ✅ | ✅ |
| 数据库批量写入 | ✅ | ✅ | ✅ |
| **检查类型扩展** | ❌ | ✅ | ✅ |
| **元素定位策略** | ❌ | ✅ | ✅ |
| **数据断言能力** | ❌ | ✅ | ❌ |
| **失败恢复重试** | ✅ | ✅ | ✅ |
| **测试数据管理** | ❌ | ✅ | ❌ |
| **并发控制隔离** | ✅ | ✅ | ✅ |
| **可视化调试** | ❌ | ✅ | ✅ |
| **环境管理** | ❌ | ✅ | ❌ |
| **集成扩展** | ❌ | ✅ | ✅ |

---

## 核心结论

除了之前分析的 3 个性能问题，还有 **9 个致命短板** 需要补齐：

### P0（必须立即解决）

1. 浏览器池化
2. Worker 并发模型
3. 失败恢复和重试机制
4. 并发控制和资源隔离

### P1（短期内补齐）

5. 检查类型扩展机制
6. 元素定位策略强化
7. 可视化调试能力
8. 集成和扩展能力

### P2（中期规划）

9. 数据断言能力
10. 测试数据管理
11. 环境管理

当前项目是一个**好的基础框架**，但距离企业级 AI 自动化测试平台还有较大差距。

---

*分析日期：2026-04-03*
