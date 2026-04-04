# Runlet Runtime Inspection and HotGo Crawl Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地真实启动 Runlet 前后端与相关服务，完成平台 API 与前端页面巡检，并基于已有 `hotgo` 系统记录真实触发一次 `crawl -> asset compile` 后，对菜单、页面、关键元素、检查资产四层结果做真实性校验，最终输出证据化报告。

**Architecture:** 本计划不建设长期 E2E 基础设施，也不默认修改 `backend/src` 或 `front/src`。执行时通过本地真实服务、一次性 Playwright 临时脚本、数据库事实查询和控制面 API 调用四条证据链完成验收；所有临时证据写入 `/tmp/runlet-runtime-inspection/`，最终结论通过报告汇总。若执行中发现产品缺陷，仅记录问题与证据，不在本计划内直接修复。

**Tech Stack:** FastAPI, SQLModel, PostgreSQL, Redis, React + Vite, Python 3.12, Playwright Python, curl, uv, npm

---

## File Structure

**Execution Notes:**

- 本计划默认不修改 `backend/src`、`front/src`、`tests/`。
- 本计划默认不创建仓库内长期保留的 E2E 配置。
- 所有一次性证据统一放在 `/tmp/runlet-runtime-inspection/`。
- 如果执行中发现需要修复的产品问题，应先完成本计划的证据采集与报告，再另起 fix spec/plan。

**Files to Create:**

- `/tmp/runlet-runtime-inspection/report.md`
  Responsibility: 汇总服务启动、API、前端页面、`hotgo` 采集正确性的最终报告。
- `/tmp/runlet-runtime-inspection/preflight.log`
  Responsibility: 记录环境预检、依赖检查、数据库与 Redis 连通性结果。
- `/tmp/runlet-runtime-inspection/backend.log`
  Responsibility: 记录后端 API 启动与运行日志。
- `/tmp/runlet-runtime-inspection/worker.log`
  Responsibility: 记录 worker 日志。
- `/tmp/runlet-runtime-inspection/scheduler.log`
  Responsibility: 记录 scheduler 日志。
- `/tmp/runlet-runtime-inspection/front.log`
  Responsibility: 记录前端 dev server 日志。
- `/tmp/runlet-runtime-inspection/cookies.txt`
  Responsibility: 保存控制台登录后的 cookie，用于后续 API 调用。
- `/tmp/runlet-runtime-inspection/api/`
  Responsibility: 保存平台 API 请求结果和状态摘要。
- `/tmp/runlet-runtime-inspection/screenshots/runlet/`
  Responsibility: 保存 Runlet 平台前端页面巡检截图。
- `/tmp/runlet-runtime-inspection/screenshots/hotgo/`
  Responsibility: 保存 `hotgo` 真实页面对照截图。
- `/tmp/runlet-runtime-inspection/runlet_console_inspection.py`
  Responsibility: 一次性 Playwright 临时脚本，巡检 Runlet 控制台主要页面。
- `/tmp/runlet-runtime-inspection/hotgo_live_inspection.py`
  Responsibility: 一次性 Playwright 临时脚本，读取 `hotgo` 真实菜单与关键页面状态。
- `/tmp/runlet-runtime-inspection/runlet_console_summary.json`
  Responsibility: 保存 Runlet 前端巡检脚本产生的页面状态、控制台错误与网络失败摘要。
- `/tmp/runlet-runtime-inspection/hotgo_live_summary.json`
  Responsibility: 保存 `hotgo` 真实页面抽样、菜单与关键元素摘要。
- `/tmp/runlet-runtime-inspection/hotgo_db_summary.json`
  Responsibility: 保存 `hotgo` 最新 snapshot 与资产层汇总数据。

**Existing References to Read While Executing:**

- `docs/superpowers/specs/2026-04-04-runlet-runtime-inspection-and-hotgo-crawl-validation-design.md`
- `docs/base_info.md`
- `README.md`
- `backend/README.md`
- `backend/src/app/main.py`
- `backend/src/app/api/endpoints/console_auth.py`
- `backend/src/app/api/endpoints/console_portal.py`
- `backend/src/app/api/endpoints/console_tasks.py`
- `backend/src/app/api/endpoints/console_assets.py`
- `backend/src/app/api/endpoints/console_results.py`
- `backend/src/app/api/endpoints/crawl.py`
- `backend/src/app/domains/auth_service/browser_login.py`
- `backend/src/app/domains/auth_service/crypto.py`
- `backend/src/app/infrastructure/db/models/systems.py`
- `backend/src/app/infrastructure/db/models/crawl.py`
- `backend/src/app/infrastructure/db/models/assets.py`
- `backend/src/app/infrastructure/db/models/jobs.py`

---

### Task 1: 建立巡检工作区并完成环境预检

**Files:**

- Create: `/tmp/runlet-runtime-inspection/report.md`
- Create: `/tmp/runlet-runtime-inspection/preflight.log`
- Create: `/tmp/runlet-runtime-inspection/api/`
- Create: `/tmp/runlet-runtime-inspection/screenshots/runlet/`
- Create: `/tmp/runlet-runtime-inspection/screenshots/hotgo/`

- [ ] **Step 1: 创建一次性巡检目录与报告骨架**

```bash
rm -rf /tmp/runlet-runtime-inspection
mkdir -p /tmp/runlet-runtime-inspection/api /tmp/runlet-runtime-inspection/screenshots/runlet /tmp/runlet-runtime-inspection/screenshots/hotgo
cat > /tmp/runlet-runtime-inspection/report.md <<'EOF'
# Runlet 联调验收报告

## 1. 服务启动结果

## 2. 平台 API 巡检结果

## 3. 平台前端 Playwright 巡检结果

## 4. HotGo 采集与编译结果

## 5. HotGo 真实页面对照结果

## 6. 问题清单

## 7. 总体结论
EOF
```

- [ ] **Step 2: 记录当前仓库状态并声明本轮不改产品代码**

Run: `cd /Users/wangpei/src/singe/Runlet && git status --short | tee /tmp/runlet-runtime-inspection/git-status.txt`
Expected: 仅记录当前脏文件状态；本轮执行不修改 `backend/src`、`front/src`、`tests/`。

- [ ] **Step 3: 检查本地依赖是否齐全**

Run:

```bash
{
  echo "== uv ==";
  uv --version;
  echo "== npm ==";
  npm --version;
  echo "== psql ==";
  psql --version;
  echo "== redis-cli ==";
  redis-cli --version;
  echo "== playwright import ==";
  cd /Users/wangpei/src/singe/Runlet/backend && uv run python -c "from playwright.async_api import async_playwright; print('playwright-ok')";
} | tee /tmp/runlet-runtime-inspection/preflight.log
```

Expected: 所有命令可执行，最后输出 `playwright-ok`。

- [ ] **Step 4: 验证后端环境文件与数据库/Redis 连通性**

Run:

```bash
test -f /Users/wangpei/src/singe/Runlet/backend/.env
PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -c "SET search_path TO runlet; SELECT 1;"
redis-cli -h 127.0.0.1 -p 6379 ping
```

Expected: `.env` 存在，PostgreSQL 返回 `1`，Redis 返回 `PONG`。

- [ ] **Step 5: 预读控制台与 HotGo 关键输入**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet
python - <<'PY'
from pathlib import Path
import re

text = Path("docs/base_info.md").read_text(encoding="utf-8")
for key in ["测试系统3", "host", "port", "database"]:
    print(key, "ok" if key in text else "missing")
print("hotgo_url", bool(re.search(r"hotgo.*https://hotgo", text, re.I | re.S)))
PY
```

Expected: `hotgo_url True`，说明执行计划所需的基础信息已在文档中存在。

---

### Task 2: 启动本地服务并记录健康状态

**Files:**

- Create: `/tmp/runlet-runtime-inspection/backend.log`
- Create: `/tmp/runlet-runtime-inspection/worker.log`
- Create: `/tmp/runlet-runtime-inspection/scheduler.log`
- Create: `/tmp/runlet-runtime-inspection/front.log`

- [ ] **Step 1: 检查 `8000` 与 `5173` 端口是否已被占用**

Run: `lsof -nP -iTCP:8000 -iTCP:5173 -sTCP:LISTEN`
Expected: 若已有旧进程，先记录 PID 和命令名；不要直接做破坏性清理。

- [ ] **Step 2: 启动后端 API 并写入日志**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet/backend
nohup uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 > /tmp/runlet-runtime-inspection/backend.log 2>&1 &
echo $! > /tmp/runlet-runtime-inspection/backend.pid
```

Expected: 进程常驻，`/tmp/runlet-runtime-inspection/backend.pid` 存在。

- [ ] **Step 3: 轮询 `/healthz` 直到 API 返回 200**

Run:

```bash
for i in $(seq 1 30); do
  code=$(curl -s -o /tmp/runlet-runtime-inspection/healthz.json -w "%{http_code}" http://127.0.0.1:8000/healthz || true)
  if [ "$code" = "200" ]; then
    echo "healthz-ok"
    break
  fi
  sleep 1
done
```

Expected: 输出 `healthz-ok`，且 `/tmp/runlet-runtime-inspection/healthz.json` 包含 `{"status":"ok"}`。

- [ ] **Step 4: 启动 worker 与 scheduler**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet/backend
nohup uv run runlet-worker > /tmp/runlet-runtime-inspection/worker.log 2>&1 &
echo $! > /tmp/runlet-runtime-inspection/worker.pid
nohup uv run runlet-scheduler > /tmp/runlet-runtime-inspection/scheduler.log 2>&1 &
echo $! > /tmp/runlet-runtime-inspection/scheduler.pid
```

Expected: 两个 PID 文件都存在，进程不应立即退出。

- [ ] **Step 5: 启动前端 dev server**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet/front
nohup npm run dev -- --host 127.0.0.1 --port 5173 > /tmp/runlet-runtime-inspection/front.log 2>&1 &
echo $! > /tmp/runlet-runtime-inspection/front.pid
```

Expected: 前端进程常驻，并在日志中监听 `http://127.0.0.1:5173`。

- [ ] **Step 6: 检查四类日志中是否已经出现异常**

Run:

```bash
rg -n "Traceback|ERROR|Exception|Address already in use|ModuleNotFoundError" /tmp/runlet-runtime-inspection/backend.log /tmp/runlet-runtime-inspection/worker.log /tmp/runlet-runtime-inspection/scheduler.log /tmp/runlet-runtime-inspection/front.log || true
```

Expected: 启动阶段没有明显异常；若有命中，先把日志片段写入报告，再决定是否继续。

---

### Task 3: 巡检平台核心 API 并定位 HotGo 系统记录

**Files:**

- Create: `/tmp/runlet-runtime-inspection/cookies.txt`
- Create: `/tmp/runlet-runtime-inspection/api/login.json`
- Create: `/tmp/runlet-runtime-inspection/api/me.json`
- Create: `/tmp/runlet-runtime-inspection/api/dashboard.json`
- Create: `/tmp/runlet-runtime-inspection/api/systems.json`
- Create: `/tmp/runlet-runtime-inspection/api/tasks.json`
- Create: `/tmp/runlet-runtime-inspection/api/assets.json`
- Create: `/tmp/runlet-runtime-inspection/api/results.json`
- Create: `/tmp/runlet-runtime-inspection/api/hotgo-system.json`

- [ ] **Step 1: 读取控制台用户名与密码**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet/backend
set -a
source .env
set +a
printf '%s\n' "${CONSOLE_USERNAME:-admin}" > /tmp/runlet-runtime-inspection/console_username.txt
printf '%s\n' "${CONSOLE_PASSWORD:-admin}" > /tmp/runlet-runtime-inspection/console_password.txt
```

Expected: 两个临时文件存在，供后续 `curl` 与 Playwright 脚本复用。

- [ ] **Step 2: 登录控制台并保存 cookie**

Run:

```bash
USERNAME=$(cat /tmp/runlet-runtime-inspection/console_username.txt)
PASSWORD=$(cat /tmp/runlet-runtime-inspection/console_password.txt)
curl -sS -c /tmp/runlet-runtime-inspection/cookies.txt \
  -H 'content-type: application/json' \
  -d "{\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" \
  http://127.0.0.1:8000/api/console/auth/login \
  | tee /tmp/runlet-runtime-inspection/api/login.json
```

Expected: 返回 `{"ok":true}`，并且 `cookies.txt` 中包含 `console_session`。

- [ ] **Step 3: 调用控制台核心读接口**

Run:

```bash
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt http://127.0.0.1:8000/api/console/auth/me | tee /tmp/runlet-runtime-inspection/api/me.json
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt http://127.0.0.1:8000/api/console/portal/dashboard | tee /tmp/runlet-runtime-inspection/api/dashboard.json
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt http://127.0.0.1:8000/api/console/portal/systems | tee /tmp/runlet-runtime-inspection/api/systems.json
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt http://127.0.0.1:8000/api/console/tasks/ | tee /tmp/runlet-runtime-inspection/api/tasks.json
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt http://127.0.0.1:8000/api/console/assets/ | tee /tmp/runlet-runtime-inspection/api/assets.json
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt "http://127.0.0.1:8000/api/console/results/?page=1&page_size=20" | tee /tmp/runlet-runtime-inspection/api/results.json
```

Expected: 各接口返回 200 且为合法 JSON；若某接口为空数组也属于可记录结果，不算立即失败。

- [ ] **Step 4: 校验核心接口 JSON 结构可以被解析**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

files = [
    "me.json",
    "dashboard.json",
    "systems.json",
    "tasks.json",
    "assets.json",
    "results.json",
]
root = Path("/tmp/runlet-runtime-inspection/api")
for name in files:
    data = json.loads((root / name).read_text())
    print(name, type(data).__name__)
PY
```

Expected: 输出每个文件的 JSON 顶层类型，不应抛出解析异常。

- [ ] **Step 5: 通过控制台系统列表定位 `hotgo`**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

systems = json.loads(Path("/tmp/runlet-runtime-inspection/api/systems.json").read_text())
matches = [item for item in systems if "hotgo" in item["name"].lower() or "hotgo" in item["base_url"].lower()]
if not matches:
    raise SystemExit("hotgo system not found in console portal systems response")
Path("/tmp/runlet-runtime-inspection/api/hotgo-system.json").write_text(json.dumps(matches[0], ensure_ascii=False, indent=2), encoding="utf-8")
print(matches[0]["id"])
PY
```

Expected: 输出一个 `hotgo` 系统 ID，并生成 `/tmp/runlet-runtime-inspection/api/hotgo-system.json`。

- [ ] **Step 6: 若控制台列表缺少 `hotgo`，使用数据库查询回退**

Run:

```bash
PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -At -c "SET search_path TO runlet; SELECT id || '|' || code || '|' || name || '|' || base_url FROM systems WHERE lower(name) LIKE '%hotgo%' OR lower(base_url) LIKE '%hotgo%' ORDER BY created_at DESC LIMIT 1;"
```

Expected: 返回一条 `id|code|name|base_url`；若仍为空，本轮验收应直接判为阻塞。

---

### Task 4: 对 Runlet 平台前端做一次性 Playwright 巡检

**Files:**

- Create: `/tmp/runlet-runtime-inspection/runlet_console_inspection.py`
- Create: `/tmp/runlet-runtime-inspection/runlet_console_summary.json`
- Create: `/tmp/runlet-runtime-inspection/screenshots/runlet/*.png`

- [ ] **Step 1: 编写一次性 Runlet 控制台巡检脚本**

```python
from pathlib import Path
import json
import asyncio
from playwright.async_api import async_playwright

ROOT = Path("/tmp/runlet-runtime-inspection")
OUT = ROOT / "runlet_console_summary.json"
PAGES = [
    ("dashboard", "http://127.0.0.1:5173/"),
    ("tasks", "http://127.0.0.1:5173/tasks"),
    ("assets", "http://127.0.0.1:5173/assets"),
    ("systems", "http://127.0.0.1:5173/systems"),
    ("results", "http://127.0.0.1:5173/results"),
]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        console_errors = []
        page_errors = []
        failed_requests = []
        page.on("console", lambda msg: console_errors.append({"type": msg.type, "text": msg.text}) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append({"url": req.url, "method": req.method}))
        await page.goto("http://127.0.0.1:5173/login", wait_until="domcontentloaded")
        await page.get_by_label("用户名").fill(Path("/tmp/runlet-runtime-inspection/console_username.txt").read_text().strip())
        await page.get_by_label("密码").fill(Path("/tmp/runlet-runtime-inspection/console_password.txt").read_text().strip())
        await page.get_by_role("button", name="登录").click()
        states = []
        for name, url in PAGES:
            await page.goto(url, wait_until="domcontentloaded")
            await page.screenshot(path=str(ROOT / "screenshots" / "runlet" / f"{name}.png"), full_page=True)
            states.append({"name": name, "url": page.url, "title": await page.title()})
        OUT.write_text(json.dumps({"pages": states, "console_errors": console_errors, "page_errors": page_errors, "failed_requests": failed_requests}, ensure_ascii=False, indent=2), encoding="utf-8")
        await browser.close()

asyncio.run(main())
```

将上述内容保存到 `/tmp/runlet-runtime-inspection/runlet_console_inspection.py`。

- [ ] **Step 2: 执行一次性前端巡检脚本**

Run: `cd /Users/wangpei/src/singe/Runlet/backend && uv run python /tmp/runlet-runtime-inspection/runlet_console_inspection.py`
Expected: 脚本退出码为 0，生成 `runlet_console_summary.json` 与 5 张页面截图。

- [ ] **Step 3: 检查巡检摘要中是否记录到前端异常**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/runlet-runtime-inspection/runlet_console_summary.json").read_text())
print("pages", len(data["pages"]))
print("console_errors", len(data["console_errors"]))
print("page_errors", len(data["page_errors"]))
print("failed_requests", len(data["failed_requests"]))
PY
```

Expected: `pages` 至少为 `5`；若其他计数大于 `0`，需要在报告中逐项记录。

- [ ] **Step 4: 复核页面主标题和导航是否基本正常**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/tmp/runlet-runtime-inspection/runlet_console_summary.json").read_text())
for item in data["pages"]:
    print(item["name"], item["url"], item["title"])
PY
```

Expected: 页面 URL 与目标路由一致，不应全部回退到 `/login`，也不应出现明显空标题。

---

### Task 5: 触发 HotGo 新采集并跟踪 `crawl -> asset compile`

**Files:**

- Create: `/tmp/runlet-runtime-inspection/api/hotgo-crawl-request.json`
- Create: `/tmp/runlet-runtime-inspection/api/hotgo-crawl-response.json`
- Create: `/tmp/runlet-runtime-inspection/api/hotgo-crawl-job.json`
- Create: `/tmp/runlet-runtime-inspection/api/hotgo-compile-job.json`
- Create: `/tmp/runlet-runtime-inspection/hotgo_db_summary.json`

- [ ] **Step 1: 读取 `hotgo` 系统 ID**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

system_id = json.loads(Path("/tmp/runlet-runtime-inspection/api/hotgo-system.json").read_text())["id"]
Path("/tmp/runlet-runtime-inspection/hotgo_system_id.txt").write_text(system_id, encoding="utf-8")
print(system_id)
PY
```

Expected: 输出 UUID，并生成 `/tmp/runlet-runtime-inspection/hotgo_system_id.txt`。

- [ ] **Step 2: 通过正式控制面接口触发一次新的 `crawl`**

Run:

```bash
cat > /tmp/runlet-runtime-inspection/api/hotgo-crawl-request.json <<'EOF'
{"crawl_scope":"full","framework_hint":"auto","max_pages":50}
EOF
SYSTEM_ID=$(cat /tmp/runlet-runtime-inspection/hotgo_system_id.txt)
curl -sS -b /tmp/runlet-runtime-inspection/cookies.txt \
  -H 'content-type: application/json' \
  -d @/tmp/runlet-runtime-inspection/api/hotgo-crawl-request.json \
  "http://127.0.0.1:8000/api/v1/systems/${SYSTEM_ID}/crawl" \
  | tee /tmp/runlet-runtime-inspection/api/hotgo-crawl-response.json
```

Expected: 返回 `status=accepted`、`job_type=crawl` 和 `job_id`。

- [ ] **Step 3: 轮询 crawl job 直到结束**

Run:

```bash
python - <<'PY'
import json
import subprocess
import time
from pathlib import Path

job_id = json.loads(Path("/tmp/runlet-runtime-inspection/api/hotgo-crawl-response.json").read_text())["job_id"]
sql = f"SET search_path TO runlet; SELECT row_to_json(t) FROM (SELECT id, job_type, status, failure_message, result_payload, started_at, finished_at FROM queued_jobs WHERE id = '{job_id}') t;"
for _ in range(120):
    out = subprocess.check_output([
        "bash", "-lc",
        f"PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -At -c \"{sql}\""
    ], text=True).strip()
    Path('/tmp/runlet-runtime-inspection/api/hotgo-crawl-job.json').write_text(out, encoding='utf-8')
    data = json.loads(out)
    if data["status"] in {"completed", "failed", "retryable_failed", "skipped"}:
        print(data["status"])
        break
    time.sleep(2)
PY
```

Expected: 最终状态应为 `completed`；否则需要把 `failure_message` 和 `result_payload` 原样写入报告。

- [ ] **Step 4: 根据最新 snapshot 定位 compile job**

Run:

```bash
python - <<'PY'
import json
import subprocess
from pathlib import Path

crawl_job = json.loads(Path("/tmp/runlet-runtime-inspection/api/hotgo-crawl-job.json").read_text())
snapshot_id = (crawl_job.get("result_payload") or {}).get("snapshot_id")
if not snapshot_id:
    raise SystemExit("crawl job missing snapshot_id")
sql = f"SET search_path TO runlet; SELECT row_to_json(t) FROM (SELECT id, job_type, status, failure_message, payload, result_payload, created_at, started_at, finished_at FROM queued_jobs WHERE job_type = 'asset_compile' AND payload->>'snapshot_id' = '{snapshot_id}' ORDER BY created_at DESC LIMIT 1) t;"
out = subprocess.check_output([
    "bash", "-lc",
    f"PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -At -c \"{sql}\""
], text=True).strip()
Path('/tmp/runlet-runtime-inspection/api/hotgo-compile-job.json').write_text(out, encoding='utf-8')
print(snapshot_id)
PY
```

Expected: 成功写出 `hotgo-compile-job.json`，且其中 `job_type=asset_compile`。

- [ ] **Step 5: 轮询 compile job 直到结束**

Run:

```bash
python - <<'PY'
import json
import subprocess
import time
from pathlib import Path

job = json.loads(Path("/tmp/runlet-runtime-inspection/api/hotgo-compile-job.json").read_text())
job_id = job["id"]
sql = f"SET search_path TO runlet; SELECT row_to_json(t) FROM (SELECT id, job_type, status, failure_message, payload, result_payload, started_at, finished_at FROM queued_jobs WHERE id = '{job_id}') t;"
for _ in range(120):
    out = subprocess.check_output([
        "bash", "-lc",
        f"PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -At -c \"{sql}\""
    ], text=True).strip()
    Path('/tmp/runlet-runtime-inspection/api/hotgo-compile-job.json').write_text(out, encoding='utf-8')
    data = json.loads(out)
    if data["status"] in {"completed", "failed", "retryable_failed", "skipped"}:
        print(data["status"])
        break
    time.sleep(2)
PY
```

Expected: 最终状态应为 `completed`；否则本轮 `hotgo` 采集正确性直接判失败。

- [ ] **Step 6: 汇总最新 snapshot 的事实层与资产层数量**

Run:

```bash
python - <<'PY'
import json
import subprocess
from pathlib import Path

system_id = Path('/tmp/runlet-runtime-inspection/hotgo_system_id.txt').read_text().strip()
crawl_job = json.loads(Path('/tmp/runlet-runtime-inspection/api/hotgo-crawl-job.json').read_text())
snapshot_id = crawl_job["result_payload"]["snapshot_id"]
sql = f"""
SET search_path TO runlet;
SELECT json_build_object(
  'snapshot_id', '{snapshot_id}',
  'pages', (SELECT count(*) FROM pages WHERE snapshot_id = '{snapshot_id}'),
  'menu_nodes', (SELECT count(*) FROM menu_nodes WHERE snapshot_id = '{snapshot_id}'),
  'page_elements', (SELECT count(*) FROM page_elements WHERE snapshot_id = '{snapshot_id}'),
  'page_assets', (SELECT count(*) FROM page_assets WHERE system_id = '{system_id}' AND compiled_from_snapshot_id = '{snapshot_id}'),
  'page_checks', (SELECT count(*) FROM page_checks pc JOIN page_assets pa ON pa.id = pc.page_asset_id WHERE pa.system_id = '{system_id}' AND pa.compiled_from_snapshot_id = '{snapshot_id}'),
  'module_plans', (SELECT count(*) FROM module_plans mp JOIN page_assets pa ON pa.id = mp.page_asset_id WHERE pa.system_id = '{system_id}' AND pa.compiled_from_snapshot_id = '{snapshot_id}')
);
"""
out = subprocess.check_output([
    "bash", "-lc",
    f"PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -At -c \"{sql}\""
], text=True).strip()
Path('/tmp/runlet-runtime-inspection/hotgo_db_summary.json').write_text(out, encoding='utf-8')
print(out)
PY
```

Expected: `pages`、`menu_nodes`、`page_elements`、`page_assets`、`page_checks`、`module_plans` 都为非零；若任一为零，需要在报告中标为高优先级问题。

---

### Task 6: 用真实浏览器对照 HotGo 页面并完成最终报告

**Files:**

- Create: `/tmp/runlet-runtime-inspection/hotgo_live_inspection.py`
- Create: `/tmp/runlet-runtime-inspection/hotgo_live_summary.json`
- Modify: `/tmp/runlet-runtime-inspection/report.md`

- [ ] **Step 1: 编写 `hotgo` 临时登录与菜单抽样脚本**

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlmodel import Session, create_engine, select

from app.config.settings import settings
from app.domains.auth_service.browser_login import PlaywrightBrowserLoginAdapter
from app.domains.auth_service.crypto import LocalCredentialCrypto
from app.infrastructure.db.models.systems import System, SystemCredential

ROOT = Path("/tmp/runlet-runtime-inspection")

async def main():
    engine = create_engine(settings.database_url.replace("+asyncpg", "+psycopg"))
    system_id = ROOT.joinpath("hotgo_system_id.txt").read_text().strip()
    with Session(engine) as session:
        system = session.get(System, system_id)
        cred = session.exec(select(SystemCredential).where(SystemCredential.system_id == system_id)).first()
    crypto = LocalCredentialCrypto()
    adapter = PlaywrightBrowserLoginAdapter(playwright_headless=True)
    result = await adapter.login(
        login_url=cred.login_url,
        username=crypto.decrypt(cred.login_username_encrypted),
        password=crypto.decrypt(cred.login_password_encrypted),
        auth_type=cred.login_auth_type,
        selectors=cred.login_selectors,
    )
    summary = {
        "system_name": system.name,
        "auth_mode": result.auth_mode,
        "cookies_count": len(result.storage_state.get("cookies", [])),
        "origins_count": len(result.storage_state.get("origins", [])),
    }
    ROOT.joinpath("hotgo_live_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

asyncio.run(main())
```

将上述内容保存到 `/tmp/runlet-runtime-inspection/hotgo_live_inspection.py`，后续按实际页面结构补充“打开首页、截图左侧菜单、抽样 3 个关键菜单页”的逻辑。优先复用库里已有 `login_selectors` 与 `ddddocr` 验证码能力，不要重新猜测登录表单。

- [ ] **Step 2: 执行 `hotgo` 临时脚本并确认真实登录成功**

Run:

```bash
cd /Users/wangpei/src/singe/Runlet/backend
uv run python /tmp/runlet-runtime-inspection/hotgo_live_inspection.py
```

Expected: 生成 `hotgo_live_summary.json`，且 `cookies_count`、`origins_count` 至少有一项大于 `0`。

- [ ] **Step 3: 在脚本中补齐真实菜单与关键页面抽样**

将脚本扩展为至少完成以下动作：

- 打开 `hotgo` 登录后的首页
- 截取左侧菜单截图到 `/tmp/runlet-runtime-inspection/screenshots/hotgo/menu.png`
- 读取至少 10 个可见菜单文本
- 进入 3 个关键页面并各保存 1 张截图
- 在每个关键页面记录至少 1 个关键交互元素文本或 role

Expected: `hotgo_live_summary.json` 中新增 `menu_labels`、`sample_pages`、`key_elements` 字段。

- [ ] **Step 4: 将真实页面摘要与数据库事实层做对照**

Run:

```bash
python - <<'PY'
import json
import subprocess
from pathlib import Path

live = json.loads(Path('/tmp/runlet-runtime-inspection/hotgo_live_summary.json').read_text())
snapshot_id = json.loads(Path('/tmp/runlet-runtime-inspection/hotgo_db_summary.json').read_text())['snapshot_id']
sql = f"""
SET search_path TO runlet;
SELECT json_build_object(
  'menu_labels', (SELECT json_agg(label ORDER BY depth, sort_order, label) FROM (SELECT DISTINCT label, depth, sort_order FROM menu_nodes WHERE snapshot_id = '{snapshot_id}' ORDER BY depth, sort_order, label LIMIT 50) t),
  'routes', (SELECT json_agg(route_path ORDER BY route_path) FROM (SELECT DISTINCT route_path FROM pages WHERE snapshot_id = '{snapshot_id}' AND route_path IS NOT NULL ORDER BY route_path LIMIT 50) t),
  'key_elements', (SELECT json_agg(element_text) FROM (SELECT DISTINCT element_text FROM page_elements WHERE snapshot_id = '{snapshot_id}' AND element_text IS NOT NULL LIMIT 50) t)
);
"""
out = subprocess.check_output([
    "bash", "-lc",
    f"PGPASSWORD='AIOps!1234' psql -h 127.0.0.1 -U aiops -d runlet -At -c \"{sql}\""
], text=True).strip()
db = json.loads(out)
print("live_menu_count", len(live.get("menu_labels", [])))
print("db_menu_count", len(db.get("menu_labels") or []))
print("db_routes_count", len(db.get("routes") or []))
print("db_key_elements_count", len(db.get("key_elements") or []))
PY
```

Expected: 数据库侧菜单、路由、元素计数均大于零；若真实页面中的多个菜单文本在 DB 侧完全缺失，应在报告中记为“漏采菜单”。

- [ ] **Step 5: 将全部证据回填到最终报告**

至少在 `/tmp/runlet-runtime-inspection/report.md` 中补齐以下内容：

- 服务启动是否成功，是否有异常日志
- 核心 API 是否可用，哪些接口出错
- Runlet 前端页面巡检是否发现控制台错误、页面错误、失败请求
- `hotgo` 的 crawl 与 compile 是否成功
- `hotgo` 的页面、菜单、关键元素、检查资产四层是否完整
- 总体结论为 `可用`、`部分可用` 或 `不可用`

Expected: 报告可以脱离终端上下文单独阅读。

- [ ] **Step 6: 在结束前做最终验证**

Run:

```bash
test -f /tmp/runlet-runtime-inspection/report.md
test -f /tmp/runlet-runtime-inspection/runlet_console_summary.json
test -f /tmp/runlet-runtime-inspection/hotgo_live_summary.json
test -f /tmp/runlet-runtime-inspection/hotgo_db_summary.json
python - <<'PY'
from pathlib import Path
for path in [
    "/tmp/runlet-runtime-inspection/report.md",
    "/tmp/runlet-runtime-inspection/runlet_console_summary.json",
    "/tmp/runlet-runtime-inspection/hotgo_live_summary.json",
    "/tmp/runlet-runtime-inspection/hotgo_db_summary.json",
]:
    print(path, Path(path).stat().st_size)
PY
```

Expected: 四个核心产物都存在且非空，然后再向用户汇报结果。
