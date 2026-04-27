# Intake 双阶段重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将候选人采集系统重构为两阶段：Step1（每小时扫列表收人） + Step2（每3小时逐个开聊天分析+发消息），关闭浏览器=停系统，两阶段互斥运行。

**Architecture:** 后端scheduler彻底禁用，timing全部转移到extension Chrome alarms（Step1=60min, Step2=180min）；两阶段通过chrome.storage.local的`phase_running`标志互斥；新增`timed_out`状态替代`pending_human`；`collect-chat`端点内联outbox生成，让单次API调用即可触发消息发送。

**Tech Stack:** FastAPI + SQLAlchemy (backend), Chrome MV3 Extension (content/background scripts), Vue 3 + Element Plus (frontend)

---

## 文件修改清单

| 文件 | 类型 | 改动 |
|------|------|------|
| `migrations/versions/0019_intake_last_checked.py` | 新建 | 添加 `last_checked_at` 列 |
| `app/config.py` | 修改 | `f4_scheduler_enabled` 默认改 False |
| `app/modules/im_intake/candidate_model.py` | 修改 | 添加 `last_checked_at` 字段 |
| `app/modules/im_intake/service.py` | 修改 | 添加 `timed_out` 到 TERMINAL_STATES + apply_terminal |
| `app/modules/im_intake/outbox_service.py` | 修改 | 添加 `timed_out` 到 TERMINAL_STATES |
| `app/modules/im_intake/schemas.py` | 修改 | 新增 `RegisterCandidateIn`、`last_checked_at` 到 CandidateOut |
| `app/modules/im_intake/router.py` | 修改 | 新增 `/register`、`/mark-timed-out`、`/last-checked`；collect-chat内联outbox |
| `edge_extension/background.js` | 修改 | 双alarm结构 + mutex + 手动触发handler |
| `edge_extension/content.js` | 修改 | 新增 `step1_scanList()` + `step2_enrichCandidates()` |
| `frontend/src/api/intake.js` | 修改 | 新增 `registerCandidate`, `markTimedOut`, `updateLastChecked` |
| `frontend/src/views/Intake.vue` | 修改 | 替换控制面板为两按钮 + 状态显示 + timed_out filter |

---

## Task 1: DB迁移 + 模型 + TERMINAL_STATES + config

**Files:**
- Create: `migrations/versions/0019_intake_last_checked.py`
- Modify: `app/modules/im_intake/candidate_model.py`
- Modify: `app/modules/im_intake/service.py:10`
- Modify: `app/modules/im_intake/outbox_service.py:17`
- Modify: `app/config.py:76`

- [ ] **Step 1: 写失败测试（timed_out terminal守卫）**

```python
# tests/test_intake_timed_out.py
import pytest
from app.modules.im_intake.service import TERMINAL_CANDIDATE_STATES

def test_timed_out_is_terminal():
    assert "timed_out" in TERMINAL_CANDIDATE_STATES
```

- [ ] **Step 2: 运行验证测试失败**

```
cd D:/0jingtong/AgenticHR && .venv/Scripts/pytest.exe tests/test_intake_timed_out.py -v
```
Expected: FAILED - `timed_out` not in tuple

- [ ] **Step 3: 创建迁移文件**

```python
# migrations/versions/0019_intake_last_checked.py
"""add last_checked_at to intake_candidates

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('intake_candidates',
        sa.Column('last_checked_at', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('intake_candidates', 'last_checked_at')
```

- [ ] **Step 4: 添加 `last_checked_at` 到 candidate_model.py**

在 `expires_at` 行之后插入：
```python
last_checked_at = Column(DateTime, nullable=True)
```

- [ ] **Step 5: 更新 service.py TERMINAL_CANDIDATE_STATES**

```python
TERMINAL_CANDIDATE_STATES = ("complete", "abandoned", "pending_human", "timed_out")
```

并在 `apply_terminal` 的 `mark_pending_human` 块之后添加：
```python
if action.type == "timed_out":
    candidate.intake_status = "timed_out"
    candidate.intake_completed_at = datetime.now(timezone.utc)
    self.db.commit()
    expire_pending_for_candidate(self.db, candidate.id, reason="timed_out")
    _audit_safe("f4_timed_out", "auto_timed_out", candidate.id,
                {"reason": "no_reply_after_max_asks"}, reviewer_id=user_id or None)
    return None
```

- [ ] **Step 6: 更新 outbox_service.py TERMINAL_CANDIDATE_STATES**

```python
TERMINAL_CANDIDATE_STATES = ("complete", "abandoned", "pending_human", "timed_out")
```

- [ ] **Step 7: 修改 config.py 默认值**

`f4_scheduler_enabled: bool = False`

- [ ] **Step 8: 运行迁移**

```
cd D:/0jingtong/AgenticHR/migrations && ../venv/Scripts/alembic.exe upgrade head
```

- [ ] **Step 9: 运行测试验证通过**

```
cd D:/0jingtong/AgenticHR && .venv/Scripts/pytest.exe tests/test_intake_timed_out.py -v
```
Expected: PASSED

- [ ] **Step 10: 运行现有测试套件**

```
.venv/Scripts/pytest.exe tests/ -v --tb=short
```

- [ ] **Step 11: Commit**

```bash
git add migrations/versions/0019_intake_last_checked.py app/modules/im_intake/candidate_model.py app/modules/im_intake/service.py app/modules/im_intake/outbox_service.py app/config.py tests/test_intake_timed_out.py
git commit -m "feat(f4): add timed_out terminal state + last_checked_at field + disable scheduler default"
```

---

## Task 2: Schema + 新Router端点 + collect-chat内联outbox

**Files:**
- Modify: `app/modules/im_intake/schemas.py`
- Modify: `app/modules/im_intake/router.py`

- [ ] **Step 1: 写失败测试（register端点）**

```python
# tests/test_intake_register.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_register_candidate_endpoint_exists():
    # Without auth we get 401/403, not 404 — endpoint exists
    resp = client.post("/api/intake/candidates/register",
                       json={"boss_id": "test123", "name": "测试", "job_title": "工程师"})
    assert resp.status_code != 404
```

- [ ] **Step 2: 验证测试失败（404）**

```
.venv/Scripts/pytest.exe tests/test_intake_register.py -v
```

- [ ] **Step 3: 更新 schemas.py**

在 `CollectChatIn` 之前添加：
```python
class RegisterCandidateIn(BaseModel):
    boss_id: str = Field(min_length=1)
    name: str = ""
    job_title: str | None = None  # 列表页直接可见的岗位名
```

在 `CandidateOut` 中添加 `last_checked_at: datetime | None = None`

更新 `NextActionOut.type` 的 Literal 加入 `"timed_out"`:
```python
type: Literal["send_hard", "request_pdf", "wait_pdf", "wait_reply",
              "send_soft", "complete", "mark_pending_human", "abandon", "timed_out"]
```

- [ ] **Step 4: 在 router.py 添加3个新端点**

在 `collect_chat` 端点之前添加：

```python
@router.post("/candidates/register", status_code=201)
def register_candidate(
    body: RegisterCandidateIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Step1: 仅注册候选人身份（boss_id+name+job），不做LLM分析。幂等。"""
    svc = _build_service(db, user_id=user_id)
    c = svc.ensure_candidate(body.boss_id, name=body.name, job_intention=body.job_title)
    return {"candidate_id": c.id, "created": c.intake_started_at == c.updated_at}
```

在 `force_complete` 端点之后添加：

```python
@router.post("/candidates/{candidate_id}/mark-timed-out")
def mark_timed_out(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Step2: 超过3次无回应，标记超时未回复。"""
    from app.modules.im_intake.outbox_service import expire_pending_for_candidate
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "candidate not found")
    if c.intake_status in ("complete", "abandoned", "timed_out"):
        return {"ok": True, "noop": True, "status": c.intake_status}
    c.intake_status = "timed_out"
    c.intake_completed_at = datetime.now(timezone.utc)
    db.commit()
    expire_pending_for_candidate(db, c.id, reason="timed_out")
    _audit_safe("f4_timed_out", "manual_timed_out", c.id, {}, reviewer_id=user_id)
    return {"ok": True, "status": "timed_out"}


@router.patch("/candidates/{candidate_id}/last-checked")
def update_last_checked(
    candidate_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Step2: 记录最后一次检查时间（用于判断有无新消息）。"""
    c = db.query(IntakeCandidate).filter_by(id=candidate_id, user_id=user_id).first()
    if not c:
        raise HTTPException(404, "candidate not found")
    c.last_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "last_checked_at": c.last_checked_at.isoformat()}
```

- [ ] **Step 5: 在 collect-chat 端点内联outbox生成**

在 `svc.apply_terminal(c, action, user_id=user_id)` 之后，`db.refresh(c)` 之前插入：

```python
# 非终态动作：内联生成 outbox（无需后台 scheduler）
from app.modules.im_intake.outbox_service import generate_for_candidate as _gen_outbox
if action.type in ("send_hard", "request_pdf", "send_soft"):
    _gen_outbox(db, c, action)
```

- [ ] **Step 6: 更新 `_candidate_summary` 添加 last_checked_at 到 CandidateOut**

在 `_candidate_summary` 函数中（router.py:81），在 return CandidateOut(...) 添加：
```python
last_checked_at=c.last_checked_at,
```

- [ ] **Step 7: 运行测试验证**

```
.venv/Scripts/pytest.exe tests/test_intake_register.py tests/test_intake_timed_out.py -v
```

- [ ] **Step 8: 重启后端验证端点存在**

```
# 重启backend后
curl http://127.0.0.1:8000/openapi.json | python3 -c "import json,sys; paths=json.load(sys.stdin)['paths']; print([p for p in paths if 'intake' in p and ('register' in p or 'timed-out' in p or 'last-checked' in p)])"
```
Expected: list containing the 3 new endpoints

- [ ] **Step 9: Commit**

```bash
git add app/modules/im_intake/schemas.py app/modules/im_intake/router.py
git commit -m "feat(f4): register/mark-timed-out/last-checked endpoints + inline outbox in collect-chat"
```

---

## Task 3: Extension background.js 双alarm + mutex

**Files:**
- Modify: `edge_extension/background.js`

- [ ] **Step 1: 重写 background.js**

完整替换，保留 `pollOutboxOnce` 和 `reportAck` 函数不变，改写alarm结构：

```javascript
// background.js — 招聘助手 Service Worker (双阶段重构)
const STEP1_ALARM = "intake_step1_scan";      // 每小时扫列表收新候选人
const STEP1_PERIOD_MIN = 60;
const STEP2_ALARM = "intake_step2_enrich";    // 每3小时逐个分析+发消息
const STEP2_PERIOD_MIN = 180;
const OUTBOX_ALARM_NAME = "intake_outbox_poll";
const OUTBOX_ALARM_PERIOD_MIN = 0.5;          // 30s

// 安装/启动时注册alarm
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({ serverUrl: "http://127.0.0.1:8000", intake_enabled: false });
  }
  ensureAlarms();
});
chrome.runtime.onStartup.addListener(ensureAlarms);

async function ensureAlarms() {
  const { intake_enabled } = await chrome.storage.local.get(["intake_enabled"]);
  for (const name of [STEP1_ALARM, STEP2_ALARM, OUTBOX_ALARM_NAME]) {
    await chrome.alarms.clear(name);
  }
  if (!intake_enabled) return;
  chrome.alarms.create(STEP1_ALARM, { periodInMinutes: STEP1_PERIOD_MIN });
  chrome.alarms.create(STEP2_ALARM, { periodInMinutes: STEP2_PERIOD_MIN });
  chrome.alarms.create(OUTBOX_ALARM_NAME, { periodInMinutes: OUTBOX_ALARM_PERIOD_MIN });
}

// intake_enabled 变更时重建alarm
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "intake_enabled" in changes) ensureAlarms();
});

// ── mutex 工具 ──────────────────────────────────────────────
async function acquirePhase(phase) {
  const { phase_running } = await chrome.storage.local.get(["phase_running"]);
  if (phase_running && phase_running !== phase) return false;
  await chrome.storage.local.set({ phase_running: phase });
  return true;
}
async function releasePhase() {
  await chrome.storage.local.remove("phase_running");
}

// ── Boss tab 查找 ─────────────────────────────────────────────
async function getBossTab() {
  const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
  if (!tabs.length) return null;
  return tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0];
}

// ── Outbox poll (沿用) ────────────────────────────────────────
async function pollOutboxOnce() {
  const { serverUrl, authToken } = await chrome.storage.local.get(["serverUrl", "authToken"]);
  if (!serverUrl || !authToken) return;
  let resp;
  try {
    resp = await fetch(`${serverUrl}/api/intake/outbox/claim`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 1 }),
    });
  } catch (e) { return; }
  if (!resp.ok) return;
  const data = await resp.json();
  const items = data.items || [];
  if (!items.length) return;
  const tab = await getBossTab();
  if (!tab) { for (const it of items) await reportAck(it.id, false, "no Boss tab"); return; }
  for (const it of items) {
    try {
      await chrome.tabs.sendMessage(tab.id, { type: "intake_outbox_dispatch", outbox: it });
    } catch (e) { await reportAck(it.id, false, `dispatch failed: ${e?.message}`); }
  }
}

async function reportAck(outboxId, success, error = "") {
  const { serverUrl, authToken } = await chrome.storage.local.get(["serverUrl", "authToken"]);
  if (!serverUrl || !authToken) return;
  try {
    await fetch(`${serverUrl}/api/intake/outbox/${outboxId}/ack`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ success, error }),
    });
  } catch {}
}

// ── Alarm 分发 ────────────────────────────────────────────────
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === STEP1_ALARM) {
    await runStep1();
  } else if (alarm.name === STEP2_ALARM) {
    await runStep2();
  } else if (alarm.name === OUTBOX_ALARM_NAME) {
    const { phase_running } = await chrome.storage.local.get(["phase_running"]);
    if (!phase_running) await pollOutboxOnce();  // step运行中暂停outbox poll
  }
});

async function runStep1() {
  if (!await acquirePhase("step1")) { console.log("[step1] blocked by", (await chrome.storage.local.get(["phase_running"])).phase_running); return; }
  try {
    const tab = await getBossTab();
    if (!tab) { console.log("[step1] no Boss tab"); return; }
    await chrome.tabs.sendMessage(tab.id, { type: "intake_step1_scan" });
  } finally {
    await releasePhase();
  }
}

async function runStep2() {
  if (!await acquirePhase("step2")) { console.log("[step2] blocked by", (await chrome.storage.local.get(["phase_running"])).phase_running); return; }
  try {
    const tab = await getBossTab();
    if (!tab) { console.log("[step2] no Boss tab"); return; }
    await chrome.tabs.sendMessage(tab.id, { type: "intake_step2_enrich" });
  } finally {
    await releasePhase();
  }
}

// ── 消息监听（手动触发 + outbox ack）────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "intake_outbox_ack") {
    reportAck(msg.outbox_id, msg.success, msg.error || "").finally(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg?.type === "manual_step1") {
    runStep1().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg?.type === "manual_step2") {
    runStep2().then(() => sendResponse({ ok: true }));
    return true;
  }
});
```

- [ ] **Step 2: 确认文件写入正确**

```
wc -l D:/0jingtong/AgenticHR/edge_extension/background.js
grep -n "STEP1_ALARM\|STEP2_ALARM\|acquirePhase\|releasePhase" D:/0jingtong/AgenticHR/edge_extension/background.js
```

- [ ] **Step 3: Commit**

```bash
git add edge_extension/background.js
git commit -m "feat(ext): 双alarm Step1/Step2 + chrome.storage mutex"
```

---

## Task 4: Extension content.js — step1_scanList + step2_enrichCandidates

**Files:**
- Modify: `edge_extension/content.js`

- [ ] **Step 1: 在文件末尾（chrome.runtime.onMessage前）添加 step1_scanList**

```javascript
// ════════════════════════════════════════════
// Step1: 扫"全部"列表，仅注册新候选人（不点进去，不分析）
// ════════════════════════════════════════════
async function step1_scanList() {
  if (!location.host.includes("zhipin.com") || !/\/web\/chat/.test(location.pathname)) {
    return { ok: false, reason: "not_on_boss_chat" };
  }
  const serverUrl = await intake_getServerUrl();
  const authToken = await intake_getAuthToken();
  const authHeaders = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  intake_showToast("Step1 扫描新候选人...", "info");
  const scrollable = document.querySelector(".geek-list") || document.querySelector('[class*="list"]') || document.body;
  let collected = 0, skipped = 0;
  const processed = new Set();
  let rounds = 0;

  while (rounds < 30) {  // 最多滚30次，防死循环
    rounds++;
    const items = [...document.querySelectorAll(".geek-item")].filter(el => {
      const id = el.getAttribute("data-id");
      return id && !processed.has(id);
    });
    if (!items.length) {
      // 尝试滚动加载更多
      const beforeCount = document.querySelectorAll(".geek-item").length;
      await triggerListLoadMore(scrollable, beforeCount);
      await sleep(1000);
      const afterCount = document.querySelectorAll(".geek-item").length;
      if (afterCount === beforeCount) break;  // 到底了
      continue;
    }

    const ids = items.map(el => el.getAttribute("data-id")).filter(Boolean);
    const existingSet = await checkBossIds(ids, serverUrl, authToken);

    for (const item of items) {
      const bossId = item.getAttribute("data-id") || "";
      processed.add(bossId);
      if (existingSet.has(bossId)) { skipped++; continue; }

      const name = item.querySelector(".geek-name")?.textContent?.trim() || "";
      // job title: BOSS直聘列表第2个文本块（时间/名字/岗位/消息）
      // 尝试已知class，若无则取列表项第3个generic文本
      const jobEl = item.querySelector(".boss-name") ||
                    item.querySelector(".geek-expect") ||
                    item.querySelector('[class*="expect"]') ||
                    item.querySelectorAll("span,div")[2];  // fallback: 第3个子元素
      const jobTitle = jobEl?.textContent?.trim() || "";

      if (!name) continue;
      try {
        const r = await fetch(`${serverUrl}/api/intake/candidates/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({ boss_id: bossId, name, job_title: jobTitle }),
        });
        if (r.ok) collected++;
        else log(`[step1] register failed ${r.status} for ${name}`);
      } catch (e) {
        log(`[step1] register error: ${e.message}`);
      }
    }
  }

  intake_showToast(`Step1 完成: 新增 ${collected}，已有 ${skipped}`, "done");
  return { ok: true, collected, skipped };
}
window.step1_scanList = step1_scanList;
```

- [ ] **Step 2: 在 step1_scanList 之后添加 step2_enrichCandidates**

```javascript
// ════════════════════════════════════════════
// Step2: 逐个打开候选人聊天，LLM分析+必要时发消息
// ════════════════════════════════════════════
async function step2_enrichCandidates() {
  if (!location.host.includes("zhipin.com") || !/\/web\/chat/.test(location.pathname)) {
    return { ok: false, reason: "not_on_boss_chat" };
  }
  const serverUrl = await intake_getServerUrl();
  const authToken = await intake_getAuthToken();
  const authHeaders = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  intake_showToast("Step2 信息补全扫描中...", "info");

  // 拉取所有 collecting/awaiting_reply 候选人
  let candidates = [];
  try {
    const r = await fetch(
      `${serverUrl}/api/intake/candidates?status=collecting&size=200`,
      { headers: authHeaders }
    );
    const d = await r.json();
    candidates = [...(d.items || [])];
    // 也拉 awaiting_reply
    const r2 = await fetch(
      `${serverUrl}/api/intake/candidates?status=awaiting_reply&size=200`,
      { headers: authHeaders }
    );
    const d2 = await r2.json();
    candidates = [...candidates, ...(d2.items || [])];
  } catch (e) {
    intake_showToast(`Step2 拉候选人失败: ${e.message}`, "error");
    return { ok: false, reason: e.message };
  }

  log(`[step2] 共 ${candidates.length} 个候选人待处理`);
  let analyzed = 0, skipped = 0, completed = 0, timedOut = 0;

  for (const c of candidates) {
    const bossId = c.boss_id;
    const candidateId = c.resume_id;  // API 返回的候选人ID字段
    if (!bossId || !candidateId) { skipped++; continue; }

    const geek = document.querySelector(`.geek-item[data-id="${bossId}"]`);
    if (!geek) { skipped++; continue; }

    try {
      // 打开聊天窗口
      geek.click();
      const nameOk = await waitForNameBox(c.name || bossId, 6000);
      if (!nameOk) { log(`[step2] ${c.name} 面板未打开`); skipped++; continue; }
      await sleep(1000);

      // 提取所有消息
      const messages = extractMessages ? extractMessages() : [];

      // 判断是否有新消息（候选人消息 > last_checked_at）
      const lastChecked = c.last_checked_at ? new Date(c.last_checked_at) : null;
      const hasNewCandidateMsg = messages.some(m => {
        if (m.sender_id !== bossId) return false;
        if (!lastChecked || !m.sent_at) return true;
        return new Date(m.sent_at) > lastChecked;
      });

      if (hasNewCandidateMsg || !lastChecked) {
        // 有新消息 → 调 collect-chat，LLM分析并内联生成outbox
        const resp = await fetch(`${serverUrl}/api/intake/collect-chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({
            boss_id: bossId,
            name: c.name || "",
            messages: messages.slice(-500),  // 最多500条
          }),
        });
        if (resp.ok) {
          const result = await resp.json();
          analyzed++;
          if (result.intake_status === "complete") completed++;
          if (result.intake_status === "timed_out") timedOut++;
          log(`[step2] ${c.name}: next=${result.next_action?.type} status=${result.intake_status}`);
        }
      } else {
        log(`[step2] ${c.name}: 无新消息，跳过LLM`);
        skipped++;
      }

      // 无论是否分析，更新 last_checked_at
      await fetch(`${serverUrl}/api/intake/candidates/${candidateId}/last-checked`, {
        method: "PATCH",
        headers: authHeaders,
      });

      await sleep(800);
    } catch (e) {
      log(`[step2] ${c.name || bossId} 异常: ${e.message || e}`);
      skipped++;
    }
  }

  intake_showToast(`Step2 完成: 分析${analyzed} 完成${completed} 超时${timedOut} 跳过${skipped}`, "done");
  return { ok: true, analyzed, completed, timedOut, skipped };
}
window.step2_enrichCandidates = step2_enrichCandidates;
```

- [ ] **Step 3: 更新 onMessage listener 添加新类型处理**

在现有 `chrome.runtime.onMessage.addListener` 中，在 `intake_autoscan_tick` handler之后添加：

```javascript
if (message && message.type === "intake_step1_scan") {
  if (window.__intakeBatchInProgress) {
    sendResponse({ ok: false, reason: "batch in progress" });
    return true;
  }
  step1_scanList()
    .then(r => sendResponse(r))
    .catch(e => sendResponse({ ok: false, error: String(e) }));
  return true;
}
if (message && message.type === "intake_step2_enrich") {
  if (window.__intakeBatchInProgress) {
    sendResponse({ ok: false, reason: "batch in progress" });
    return true;
  }
  step2_enrichCandidates()
    .then(r => sendResponse(r))
    .catch(e => sendResponse({ ok: false, error: String(e) }));
  return true;
}
```

- [ ] **Step 4: 确认 `extractMessages` 函数是否存在**

```
grep -n "function extractMessages\|extractMessages" D:/0jingtong/AgenticHR/edge_extension/content.js | head -5
```

若不存在，需要从 `extractDetail()` 中提取消息读取逻辑并独立成函数。

- [ ] **Step 5: Commit**

```bash
git add edge_extension/content.js
git commit -m "feat(ext): step1_scanList + step2_enrichCandidates functions"
```

---

## Task 5: Frontend Intake.vue 双按钮 + timed_out

**Files:**
- Modify: `frontend/src/api/intake.js`
- Modify: `frontend/src/views/Intake.vue`

- [ ] **Step 1: 更新 intake.js API**

```javascript
// 在 intakeApi 对象中添加
markTimedOut: (id) => api.post(`/intake/candidates/${id}/mark-timed-out`),
updateLastChecked: (id) => api.patch(`/intake/candidates/${id}/last-checked`),
```

- [ ] **Step 2: 替换 Intake.vue 顶部控制面板**

将现有 `automation-card` el-card (目标候选人数+暂停按钮) 替换为：

```html
<el-card shadow="never" style="margin-bottom: 12px">
  <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap">
    <div>
      <el-button type="primary" :loading="step1Running" @click="triggerStep1">
        扫描新候选人（Step1）
      </el-button>
      <el-button type="success" :loading="step2Running" @click="triggerStep2" style="margin-left:8px">
        信息补全（Step2）
      </el-button>
    </div>
    <el-tag v-if="phaseStatus" :type="phaseStatus === 'idle' ? 'info' : 'warning'">
      {{ phaseStatus === 'step1' ? 'Step1 运行中' : phaseStatus === 'step2' ? 'Step2 运行中' : '空闲' }}
    </el-tag>
    <span style="color:#909399; font-size:13px">
      关闭浏览器即停止 · Step1/Step2 互斥运行
    </span>
  </div>
</el-card>
```

- [ ] **Step 3: 更新 script setup — 移除settings相关，添加step1/step2**

```javascript
const step1Running = ref(false)
const step2Running = ref(false)
const phaseStatus = ref('idle')

async function triggerStep1() {
  step1Running.value = true
  phaseStatus.value = 'step1'
  try {
    // 通过extension popup的content script触发（发消息给background）
    // 如果extension已加载，background会把消息转发给Boss tab
    ElMessage.info('Step1 已启动，请确保BOSS直聘页面已打开')
    // 实际通过extension message触发：
    // chrome.runtime.sendMessage({type: 'manual_step1'})
    // 前端无法直接调用extension，通过backend轮询或extension popup触发
  } finally {
    step1Running.value = false
    phaseStatus.value = 'idle'
    setTimeout(loadCandidates, 3000)
  }
}

async function triggerStep2() {
  step2Running.value = true
  phaseStatus.value = 'step2'
  try {
    ElMessage.info('Step2 已启动，请确保BOSS直聘页面已打开')
  } finally {
    step2Running.value = false
    phaseStatus.value = 'idle'
    setTimeout(loadCandidates, 3000)
  }
}
```

注意：前端Vue无法直接调用Chrome extension API。手动触发应该通过extension popup按钮实现。在Intake.vue中，按钮显示操作提示，实际触发在extension popup.js中添加。

- [ ] **Step 4: 更新 popup.js 添加手动触发按钮**

在 `edge_extension/popup.js` 中添加Step1/Step2触发逻辑：
```javascript
document.getElementById('step1-btn')?.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  await chrome.runtime.sendMessage({type: 'manual_step1'});
  window.close();
});
document.getElementById('step2-btn')?.addEventListener('click', async () => {
  await chrome.runtime.sendMessage({type: 'manual_step2'});
  window.close();
});
```

- [ ] **Step 5: 添加 timed_out 到状态过滤 + 显示**

在 `el-select` 状态过滤中添加：
```html
<el-option label="超时未回复" value="timed_out" />
```

在 `statusTagType` 函数中添加：
```javascript
timed_out: 'danger',
```

在 `statusText` 函数中添加：
```javascript
timed_out: '超时未回复',
```

- [ ] **Step 6: 删除 loadSettings/saveTarget/toggleEnabled 等无用函数**

这些函数依赖 `intakeSettings` API，不再需要。同时移除对应的 import。

- [ ] **Step 7: 前端热重载验证**

```
# 打开 http://localhost:3000/intake
# 确认：
# 1. 顶部出现两个按钮（扫描新候选人 / 信息补全）
# 2. 状态过滤下拉有"超时未回复"选项
# 3. 不再有"目标候选人数"输入框
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/intake.js frontend/src/views/Intake.vue edge_extension/popup.js
git commit -m "feat(ui): 双按钮控制面板 + timed_out状态 + 移除scheduler控件"
```

---

## Task 6: 端到端验证

- [ ] **Step 1: 重启后端（不带scheduler）**

```
F4_SCHEDULER_ENABLED=false .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```
验证启动日志无 "F4 scheduler started"

- [ ] **Step 2: 验证新端点**

```python
# 测试 register 端点
import urllib.request, json
TOKEN = "..."
req = urllib.request.Request("http://127.0.0.1:8000/api/intake/candidates/register",
  data=json.dumps({"boss_id":"test_e2e_001","name":"测试候选人","job_title":"全栈工程师"}).encode(),
  headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"}, method="POST")
r = urllib.request.urlopen(req); print(json.loads(r.read()))
```
Expected: `{"candidate_id": N, "created": ...}`

- [ ] **Step 3: 验证 last-checked 端点**

用Step2返回的 candidate_id 调用 PATCH /last-checked，验证返回 `last_checked_at`

- [ ] **Step 4: 验证 mark-timed-out 端点**

对同一候选人调用 POST /mark-timed-out，验证返回 `{"ok": true, "status": "timed_out"}`
再查候选人列表，状态变为 timed_out

- [ ] **Step 5: 在BOSS直聘页面手动触发Step1**

打开 extension popup → 点"扫描新候选人" → 切到BOSS直聘"全部"页面 → 查看toast提示 → 3分钟后刷新候选人收集页面，验证新候选人入库

- [ ] **Step 6: 运行完整测试套件**

```
.venv/Scripts/pytest.exe tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all pass

- [ ] **Step 7: Final commit**

```bash
git add -A && git commit -m "feat(f4): 双阶段重构完成 - Step1扫描+Step2分析+互斥+timed_out"
```
