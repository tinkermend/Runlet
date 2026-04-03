# Frontend Platform UI Foundation

- Primary workflow: create and schedule inspection task
- Visual emphasis: task status, system state, last run result
- Primary CTAs: 新建检查任务 / 立即运行 / 去接入系统

---

## Design System

### Style

**Dark Mode (OLED)** — deep black backgrounds, high contrast, WCAG AAA compliant.

- Mode: Dark only
- Best for: coding platforms, monitoring dashboards, low-light environments
- Performance: Excellent (OLED power efficient)

### Color Tokens

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-primary` | `#0F172A` | Primary surfaces, cards |
| `--color-on-primary` | `#FFFFFF` | Text on primary |
| `--color-secondary` | `#1E293B` | Secondary surfaces, sidebars |
| `--color-accent` | `#22C55E` | CTAs, success states, active indicators |
| `--color-background` | `#020617` | Page background |
| `--color-foreground` | `#F8FAFC` | Primary text |
| `--color-muted` | `#1A1E2F` | Muted backgrounds, hover states |
| `--color-border` | `#334155` | Borders, dividers |
| `--color-destructive` | `#EF4444` | Error states, destructive actions |
| `--color-ring` | `#0F172A` | Focus rings |

**Status color extensions:**

| State | Color | Usage |
|-------|-------|-------|
| Success / Running | `#22C55E` | Task running, check passed |
| Warning / Onboarding | `#F59E0B` | System onboarding in progress |
| Error / Failed | `#EF4444` | Task failed, check error |
| Neutral / Idle | `#64748B` | Disabled, not scheduled |
| Info | `#3B82F6` | Informational badges |

### Typography

**Font:** Plus Jakarta Sans (single family, variable weight)

```css
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,400;0,600;0,700;0,800;1,400&display=swap');
```

| Scale | Size | Weight | Usage |
|-------|------|--------|-------|
| Display | 32px | 800 | Page titles |
| Heading 1 | 24px | 700 | Section headings |
| Heading 2 | 18px | 600 | Card titles, sub-sections |
| Body | 16px | 400 | Primary content |
| Label | 14px | 500 | Form labels, table headers |
| Caption | 12px | 400 | Metadata, timestamps |

Line height: 1.5–1.75 for body text. Minimum 16px body to avoid iOS auto-zoom.

### Spacing Scale

4pt/8dp incremental system:

| Token | Value | Usage |
|-------|-------|-------|
| `space-1` | 4px | Tight gaps |
| `space-2` | 8px | Component internal padding |
| `space-3` | 12px | Small gaps |
| `space-4` | 16px | Standard padding |
| `space-6` | 24px | Section gaps |
| `space-8` | 32px | Large section spacing |
| `space-12` | 48px | Page-level spacing |

### Effects

- Minimal glow: `text-shadow: 0 0 10px rgba(34, 197, 94, 0.3)` for accent elements
- Card shadow: `box-shadow: 0 1px 3px rgba(0,0,0,0.5)` on dark surfaces
- Border radius: 8px for cards, 6px for inputs, 4px for badges
- Transitions: 150–300ms ease-out for enter, ease-in for exit

---

## Information Hierarchy

### Dashboard

Priority order (top to bottom, left to right):

1. **Summary cards** — today's run count, active tasks, systems count, recent failures
2. **Recent exceptions** — last 5 failed runs with system + task name + timestamp
3. **Quick actions** — 新建检查任务, 去接入系统

### Task List

Priority order:

1. **Task name + system name** (primary identity)
2. **Status badge** (running / idle / failed / disabled)
3. **Last run result + timestamp**
4. **Schedule preset** (hourly / daily / manual)
5. **Actions** (立即运行, 编辑, 禁用)

### Asset Browser

Priority order:

1. **System name** (grouping header)
2. **Page name + check item label** (business-friendly)
3. **Asset version + drift status**
4. **Raw facts** — only in detail expansion, never in list view

---

## Navigation Structure

Left sidebar navigation (desktop), collapsible:

| Item | Route | Icon |
|------|-------|------|
| Dashboard | `/dashboard` | LayoutDashboard |
| 检查任务 | `/tasks` | ClipboardCheck |
| 采集资产 | `/assets` | Database |
| 系统接入 | `/systems` | Server |
| 运行结果 | `/results` | Activity |

Active state: accent color (`#22C55E`) left border + text, muted background.

---

## Responsive Breakpoints

| Breakpoint | Width | Layout |
|------------|-------|--------|
| Mobile | 375px | Single column, bottom nav |
| Tablet | 768px | Sidebar collapsed, main content |
| Desktop | 1024px | Sidebar expanded (240px), main content |
| Wide | 1440px | Sidebar + main + max-w-6xl content |

---

## Accessibility Requirements

- Contrast: 4.5:1 minimum for all text (WCAG AA)
- Focus rings: 2px solid `#22C55E` on all interactive elements
- Keyboard navigation: full tab order support
- ARIA labels on all icon-only buttons
- No color-only status indicators (always pair with icon or text)
- `prefers-reduced-motion` respected for all animations

---

## Anti-Patterns to Avoid

- No emojis as icons — use Lucide React SVG icons
- No raw `page_check`, `published_job`, `script_render` jargon in primary views
- No `storage_state` or auth internals exposed in UI
- No horizontal scroll on mobile
- No placeholder-only form labels
- No color-only status communication
