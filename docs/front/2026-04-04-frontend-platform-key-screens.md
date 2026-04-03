# Frontend Platform Key Screens

Wireframe descriptions and interaction guidance for each primary screen.

---

## 1. Login Page (`/login`)

**Layout:** Centered card on dark background

```
┌─────────────────────────────────────┐
│                                     │
│         [Runlet Logo]               │
│      登录 Runlet 平台               │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ 用户名                      │    │
│  │ [________________________]  │    │
│  │                             │    │
│  │ 密码                        │    │
│  │ [________________] [👁]     │    │
│  │                             │    │
│  │ [错误提示 banner - red]      │    │
│  │                             │    │
│  │ [      登录      ] (accent) │    │
│  └─────────────────────────────┘    │
│                                     │
└─────────────────────────────────────┘
```

**Interactions:**
- Submit on Enter key
- Loading spinner on button during request
- Error banner below password field on 401
- Auto-redirect to `/dashboard` on success
- Redirect to `/login` if unauthenticated on any protected route

---

## 2. Dashboard (`/dashboard`)

**Layout:** Summary cards row + recent exceptions list

```
┌──────────────────────────────────────────────────────┐
│ [Sidebar Nav]  │  Dashboard                          │
│                │                                     │
│  Dashboard  ◀  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌────┐ │
│  检查任务      │  │今日   │ │活跃  │ │系统  │ │异常│ │
│  采集资产      │  │运行   │ │任务  │ │数量  │ │次数│ │
│  系统接入      │  │  42  │ │  8  │ │  3  │ │  2 │ │
│  运行结果      │  └──────┘ └──────┘ └──────┘ └────┘ │
│                │                                     │
│                │  最近异常                           │
│                │  ┌────────────────────────────────┐ │
│                │  │ ● 用户列表巡检  系统A  2m ago  │ │
│                │  │ ● 登录检查     系统B  1h ago   │ │
│                │  └────────────────────────────────┘ │
│                │                                     │
│                │  [新建检查任务]  [去接入系统]        │
└──────────────────────────────────────────────────────┘
```

**Cards:** 今日运行次数 / 活跃任务数 / 系统数量 / 近24h异常数

**Recent exceptions:** task name + system name + status badge + relative timestamp

**Quick actions:** Primary CTA "新建检查任务" (accent), Secondary "去接入系统"

---

## 3. Task List (`/tasks`)

**Layout:** Filter bar + table/card list

```
┌──────────────────────────────────────────────────────┐
│  检查任务                    [+ 新建检查任务]         │
│                                                      │
│  [全部系统 ▼]  [全部状态 ▼]  [搜索任务名...]         │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 任务名称      系统    状态    上次运行  操作  │    │
│  ├──────────────────────────────────────────────┤    │
│  │ 用户列表巡检  系统A  ● 运行中  2m ago  [▶][⋮]│    │
│  │ 登录检查      系统B  ● 失败    1h ago  [▶][⋮]│    │
│  │ 菜单完整性    系统A  ○ 空闲    3h ago  [▶][⋮]│    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Status badges:** 运行中 (green) / 失败 (red) / 空闲 (gray) / 已禁用 (muted)

**Actions per row:** 立即运行 (▶), overflow menu (⋮) with 编辑/禁用/删除

---

## 4. Task Create Wizard (`/tasks/new`)

**Layout:** Multi-step wizard with progress indicator

```
Step 1 of 3: 选择检查目标
─────────────────────────────────────────
  选择系统:
  ○ 系统A (ready)
  ○ 系统B (onboarding)

  选择页面:
  ○ 用户管理 > 用户列表
  ○ 用户管理 > 用户详情

  选择检查项:
  ☑ 菜单完整性
  ☑ 页面元素存在性

Step 2 of 3: 配置参数
─────────────────────────────────────────
  严格程度: [宽松 ○──●──○ 严格]
  超时时间: [30] 秒

Step 3 of 3: 调度设置
─────────────────────────────────────────
  调度频率:
  ○ 每小时
  ○ 每天
  ○ 手动触发

  任务名称: [用户列表巡检_____________]

  [上一步]  [创建任务] (disabled until valid)
```

**Wizard rules:**
- "创建任务" button disabled until all required fields filled
- Back navigation preserves selections
- Step indicator shows current/total steps
- Confirmation step before submit

---

## 5. Task Detail (`/tasks/:id`)

**Layout:** Header + tabs

```
┌──────────────────────────────────────────────────────┐
│  ← 检查任务                                          │
│                                                      │
│  用户列表巡检                    ● 运行中             │
│  系统A · 每小时                  [立即运行] [⋮]      │
│                                                      │
│  [概览] [调度] [运行记录] [资产来源]                  │
│  ─────────────────────────────────────────────────   │
│  概览 tab:                                           │
│    上次运行: 2m ago · 成功                           │
│    成功率: 94% (last 30 days)                        │
│    检查项: 菜单完整性, 页面元素存在性                 │
│                                                      │
│  运行记录 tab:                                       │
│    ┌──────────────────────────────────────────────┐  │
│    │ 时间          状态    耗时   详情             │  │
│    │ 2m ago        ● 成功  1.2s  [查看]           │  │
│    │ 1h ago        ● 失败  0.8s  [查看]           │  │
│    └──────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

**Tabs:** 概览 / 调度 / 运行记录 / 资产来源

**Raw facts:** only visible in 资产来源 tab, collapsed by default

---

## 6. Asset Browser (`/assets`)

**Layout:** System-grouped page/check list

```
┌──────────────────────────────────────────────────────┐
│  采集资产                                            │
│                                                      │
│  [全部系统 ▼]  [搜索页面...]                         │
│                                                      │
│  系统A                                               │
│  ├── 用户管理                                        │
│  │   ├── 用户列表  [菜单完整性] [元素存在性]  v2.1   │
│  │   └── 用户详情  [元素存在性]               v1.0   │
│  └── 权限管理                                        │
│      └── 角色列表  [菜单完整性]               v1.3   │
│                                                      │
│  系统B                                               │
│  └── 登录页面      [登录流程]                 v0.9   │
└──────────────────────────────────────────────────────┘
```

**Rules:**
- Raw facts (原始菜单事实, page_elements) NOT visible in list view
- Only business-friendly labels: page name + check item label
- Asset version shown as badge
- Click row → asset detail page

---

## 7. Asset Detail (`/assets/:id`)

**Layout:** Header + sections, raw facts in collapsible section

```
┌──────────────────────────────────────────────────────┐
│  ← 采集资产                                          │
│                                                      │
│  用户列表                                            │
│  系统A · v2.1 · 2026-04-03 采集                     │
│                                                      │
│  检查项                                              │
│  ┌──────────────────────────────────────────────┐    │
│  │ ✓ 菜单完整性    正常                         │    │
│  │ ✓ 页面元素存在性 正常                         │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ▶ 原始采集数据 (展开查看)                           │
│  ┌──────────────────────────────────────────────┐    │
│  │ [collapsed by default]                       │    │
│  │ menu_items: [...]                            │    │
│  │ page_elements: [...]                         │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Raw facts:** collapsed by default, expandable, labeled "原始采集数据"

---

## 8. System List (`/systems`)

**Layout:** Card grid with onboarding status

```
┌──────────────────────────────────────────────────────┐
│  系统接入                        [+ 接入新系统]       │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ 系统A        │  │ 系统B        │                  │
│  │ ● 已就绪     │  │ ◐ 接入中     │                  │
│  │ 3个任务      │  │ 等待采集完成 │                  │
│  │ [查看资产]   │  │ [查看进度]   │                  │
│  └──────────────┘  └──────────────┘                  │
└──────────────────────────────────────────────────────┘
```

**Status:** ready (green) / onboarding (amber) / failed (red)

---

## 9. System Onboarding Form (`/systems/new`)

**Layout:** Guided form, single page

```
┌──────────────────────────────────────────────────────┐
│  接入新系统                                          │
│                                                      │
│  系统名称 *                                          │
│  [_________________________________]                 │
│                                                      │
│  系统地址 *                                          │
│  [https://___________________________]               │
│                                                      │
│  登录方式                                            │
│  ○ 用户名密码  ○ Cookie  ○ 无需登录                  │
│                                                      │
│  [用户名密码 fields shown conditionally]             │
│                                                      │
│  备注                                                │
│  [_________________________________]                 │
│                                                      │
│  [取消]  [开始接入]                                  │
└──────────────────────────────────────────────────────┘
```

**Rules:**
- No `storage_state` or raw auth fields exposed
- Progressive disclosure: auth fields shown based on login type selection
- Required fields marked with *
- "开始接入" triggers backend onboarding flow

---

## 10. Run Results (`/results`)

**Layout:** Filter bar + results table

```
┌──────────────────────────────────────────────────────┐
│  运行结果                                            │
│                                                      │
│  [全部系统 ▼]  [全部任务 ▼]  [全部状态 ▼]  [日期范围]│
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 时间      任务名称    系统   状态   耗时  详情│    │
│  ├──────────────────────────────────────────────┤    │
│  │ 2m ago   用户列表巡检 系统A  ● 成功  1.2s [查看]│  │
│  │ 1h ago   登录检查     系统B  ● 失败  0.8s [查看]│  │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  [← 上一页]  第1页/共5页  [下一页 →]                 │
└──────────────────────────────────────────────────────┘
```

**Filters:** system / task / status / date range

**Pagination:** server-side, 20 items per page

---

## Design Compliance Checklist

- [x] Task-centric navigation wins over platform-operator navigation
- [x] Raw facts only appear in secondary or detail views (asset detail, task 资产来源 tab)
- [x] System onboarding is a guided form, not a low-level control panel
- [x] No `storage_state`, `page_check`, `published_job`, `script_render` jargon in primary views
- [x] Status always communicated with icon + color + text (not color alone)
- [x] Primary CTAs: 新建检查任务 / 立即运行 / 去接入系统
