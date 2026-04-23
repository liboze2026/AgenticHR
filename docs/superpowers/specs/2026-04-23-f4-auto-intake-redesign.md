# F4 设计 v2（重启）：Boss IM 全自动采集 — Extension-Driven

**Status**: Accepted — supersedes [2026-04-22-f4-boss-im-intake-design.md](2026-04-22-f4-boss-im-intake-design.md)
**Date**: 2026-04-23
**Phase**: M3 / F4
**Supersedes**: 原 F4 "后端 Playwright 守护" 方案（未落地、已弃用）
**Prereqs**: F3.1 单人手动采集（已交付，前称 F5）、F3.2 批量按 criteria 采集（已交付，前称 F6）

---

## 1. 命名约定变更

原 F5 = **F3.1 单人手动采集**（Boss 聊天页插件按钮触发、后端 `/api/intake/collect-chat` 做决策）
原 F6 = **F3.2 批量按 criteria 采集**（推荐页左栏遍历 + `jobs.batch_collect_criteria` 过滤）
F4 = **全自动采集 = F3.1 + F3.2 + 自循环**（本文档）

> F3 家族语义统一：都是 Boss 入口的自动化。F3.x 是手段，F4 是终态（零 HITL）。
> 文档/代码/标识符完整改名（不改动迁移 revision ID，改文件注释）。

## 2. 目标

把 F3.1 的"单人一次触发"进化为"定时自动跑全 chat/index"：
- **HR 不需手点**。插件后台 `chrome.alarms` 定时（默认 10 min）触发一次遍历
- **范围**：`zhipin.com/web/chat/index` 左栏所有对话（不只是推荐页新招呼）
- **每人**：跑一次 F3.1 `intake_runOrchestrator`（见 §6）
- **批次上限**：`f4_batch_cap`（默认 20/轮），同时受后端 `boss_max_operations_per_day` 限制
- **终止态自动流转**：complete / pending_human / abandoned 全由后端 `decide_next_action` 回传，插件按返回值 apply
- **全程零 HITL**。硬性 3 次问不到 → `pending_human`，72h 无 PDF → `abandoned`

**非目标**：F4 不动 F1/F2 评分、F6 面邀、数据库 schema（除 audit_events 新增 stage 外）。

## 3. 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Chrome Extension (edge_extension/)                         │
│                                                             │
│  background.js (service worker)                             │
│  ┌───────────────────────────────────────────────────┐      │
│  │ chrome.alarms "intakeAutoScan" (period 10 min)    │      │
│  │   └─ query active tab on zhipin.com/web/chat/*    │      │
│  │       └─ inject content script msg AUTO_SCAN_TICK │      │
│  └───────────────────────────────────────────────────┘      │
│                                                             │
│  content.js (chat/index injected)                           │
│  ┌───────────────────────────────────────────────────┐      │
│  │ intake_autoScanTick()                             │      │
│  │  1. GET /api/intake/daily-cap → 剩余额度          │      │
│  │  2. 扫左栏 .geek-item → [{boss_id, name, job,     │      │
│  │     hasUnread, lastReplyAt}...]                   │      │
│  │  3. 按后端 ranking 返回顺序（新候选 > 已问未答    │      │
│  │     24h > 待收 PDF）截取前 N （N=min(cap, 20)）   │      │
│  │  4. for each → click geek-item → wait DOM →       │      │
│  │     reuse intake_runOrchestrator()                │      │
│  │  5. 每人完成后暂停 3–8s 随机（反检测）            │      │
│  │  6. emit audit-ish PATCH /autoscan/tick-stats     │      │
│  └───────────────────────────────────────────────────┘      │
│                                                             │
│  popup.html                                                 │
│  ┌───────────────────────────────────────────────────┐      │
│  │ "自动采集" 开关 + "立即扫一次" 按钮 + 今日计数     │      │
│  └───────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Backend (FastAPI, REST only — no scheduler, no Playwright) │
│                                                             │
│  /api/intake/collect-chat    ← F3.1 已有                     │
│  /api/intake/candidates/{id}/ack-sent          ← F3.1 已有   │
│  /api/intake/candidates/{id}/start-conversation ← F3.1 已有  │
│  /api/intake/daily-cap (新)  → {used, max, remaining}        │
│  /api/intake/autoscan/rank (新) → list ordered by priority   │
│  /api/intake/autoscan/tick-stats (新) → 记录扫描批次统计     │
│                                                             │
│  service.py analyze_chat/record_asked/apply_terminal        │
│    - 每一步写 audit_events stage=F4_*                        │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 路线对比（为何弃用原 F4 后端 Playwright daemon）

| 维度 | 原 F4 (后端 Playwright) | 新 F4 (extension) |
|---|---|---|
| 依赖 | Playwright + APScheduler + 守护进程 + 用户数据目录 | 无额外依赖，复用已有 Chrome 扩展 |
| HR 在场 | 不需要（浏览器跑后端上） | 需要浏览器开着（但 HR 本来就要盯着） |
| DOM 维护 | 后端代码里维护 selector | content script 里维护，前端改动即时生效 |
| 被反检测风险 | 高（独立 user_data_dir + headless signature） | 低（复用 HR 自己的浏览器 session） |
| 已跑通的代码 | ~0（F3.1/F3.2 未用到后端 Playwright 路径） | 99%（复用 F3.1/F3.2 content.js + REST） |
| 跨机器扩展 | 易（起多个 daemon） | 每 HR 一个浏览器（本场景足够） |

**结论**：extension 路线代码复用最大化、风险最低、已验证的资产最大化。

## 4. 数据模型变更

**无 schema 变更**。只新增 `audit_events.stage` 枚举值（非 DDL，代码侧定义）：

| stage | 触发点 |
|---|---|
| `F4_autoscan_tick` | `intake_autoScanTick` 开始，元数据：`{cap_remaining, candidates_found, batch_size}` |
| `F4_candidate_enter` | 插件开始处理某候选人，`{candidate_id, boss_id}` |
| `F4_extract_history` | `analyze_chat` 解析历史对话得到 slot，`{slot_keys, source}` |
| `F4_question_sent` | `record_asked(send_hard/send_soft)`，`{action_type, slot_keys, ask_count}` |
| `F4_pdf_requested` | `record_asked(request_pdf)` |
| `F4_pdf_received` | `collect-chat` 带 `pdf_present=true` |
| `F4_completed` | `apply_terminal(complete)`，`{promoted_resume_id}` |
| `F4_pending_human` | `apply_terminal(mark_pending_human)` |
| `F4_abandoned` | `apply_terminal(abandon)` |

audit_events 表已有（M2 baseline），只差代码侧 `write_audit_event(...)` 调用。

## 5. API 新增

### 5.1 `GET /api/intake/daily-cap`

```json
→ { "used": 23, "max": 200, "remaining": 177 }
```

`used` = 当日 `audit_events` 中 `stage IN ('F3_greeted','F4_question_sent','F4_pdf_requested')` 计数
`max` = `settings.boss_max_operations_per_day`

### 5.2 `GET /api/intake/autoscan/rank?boss_ids=bx1,bx2,...`

输入：插件抓到的 chat/index 左栏 boss_id 列表（可有无关人）
输出：按优先级排序的 `intake_candidates.id` 列表 + 建议批次上限

```json
→ {
  "ordered": [
    {"candidate_id": 5, "boss_id": "bx1", "priority": "new_candidate"},
    {"candidate_id": 3, "boss_id": "bx3", "priority": "awaiting_reply_stale"},
    {"candidate_id": 7, "boss_id": "bx2", "priority": "pdf_pending"}
  ],
  "batch_cap": 20,
  "daily_cap_remaining": 177
}
```

优先级（后端逻辑）：
1. `new_candidate`：chat/index 有此 boss_id 但 `intake_candidates` 无
2. `awaiting_reply_stale`：`intake_status='awaiting_reply'` 且最近 asked_at ≥ 24h 前
3. `pdf_pending`：硬性已齐 + PDF 未到 + asked_at < 72h
4. 其他（complete/abandoned/24h 内已问）不进队

### 5.3 `POST /api/intake/autoscan/tick-stats`

```json
body: { "candidates_seen": 35, "batch_size": 10, "succeeded": 8, "failed": 2 }
→ { "audit_event_id": 1234 }
```

写入一条 `F4_autoscan_tick` audit。

## 6. Extension 侧实现

### 6.1 `background.js` — chrome.alarms 服务工作者

```javascript
chrome.alarms.create("intakeAutoScan", { periodInMinutes: 10 });
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "intakeAutoScan") return;
  const { intakeAutoScanEnabled } = await chrome.storage.local.get("intakeAutoScanEnabled");
  if (!intakeAutoScanEnabled) return;
  const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/web/chat/*" });
  if (tabs.length === 0) return;
  chrome.tabs.sendMessage(tabs[0].id, { type: "AUTO_SCAN_TICK" });
});
```

### 6.2 `content.js` — 新增 `intake_autoScanTick`

```javascript
async function intake_autoScanTick() {
  const cap = await fetch("/api/intake/daily-cap").then(r => r.json());
  if (cap.remaining <= 0) return;
  const allBossIds = Array.from(document.querySelectorAll(".geek-item[data-id]"))
    .map(el => el.getAttribute("data-id"));
  const rank = await fetch(`/api/intake/autoscan/rank?boss_ids=${allBossIds.join(",")}`)
    .then(r => r.json());
  const batch = rank.ordered.slice(0, Math.min(rank.batch_cap, cap.remaining));
  let succeeded = 0, failed = 0;
  for (const item of batch) {
    try {
      document.querySelector(`.geek-item[data-id="${item.boss_id}"]`)?.click();
      await intake_waitFor(() => !!document.querySelector(".chat-conversation"), 5000);
      await intake_runOrchestrator({ silent: true });
      succeeded++;
      await sleep(3000 + Math.random() * 5000);
    } catch (e) { failed++; }
  }
  await fetch("/api/intake/autoscan/tick-stats", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidates_seen: allBossIds.length, batch_size: batch.length, succeeded, failed })
  });
}
```

### 6.3 `popup.html` — 加开关

```html
<section id="autoScanSection">
  <h3>F4 全自动采集</h3>
  <label><input type="checkbox" id="autoScanToggle"> 启用自动扫描（每 10 min）</label>
  <button id="autoScanNow">立即扫一次</button>
  <p id="autoScanStats">今日: 0/200</p>
</section>
```

`popup.js` 绑定：
- 切换开关 → `chrome.storage.local.set({ intakeAutoScanEnabled })`
- "立即扫一次" → sendMessage AUTO_SCAN_TICK（跟 alarm 一样的入口）
- 页面打开时 GET /daily-cap 填 stats

### 6.4 函数/ID 改名（F3.1 旧前缀清理）

| 旧 | 新 |
|---|---|
| `f5_runIntakeOrchestrator` | `intake_runOrchestrator` |
| `f5_typeAndSendChatMessage` | `intake_typeAndSendChatMessage` |
| `f5_clickRequestResumeButton` | `intake_clickRequestResumeButton` |
| `f5_checkPdfReceived` | `intake_checkPdfReceived` |
| `f5_getQueryParam/getServerUrl/getAuthToken/postJSON/waitFor/showIntakeToast` | `intake_*` 同名 |
| element `#f5-intake-toast` | `#intake-toast` |

## 7. 后端删除清单

| 文件/位置 | 动作 |
|---|---|
| `app/main.py:35-72` (F4 scheduler startup block) | **删** |
| `app/modules/im_intake/scheduler.py` (whole file) | **删** |
| `app/modules/im_intake/router.py` — `/scheduler/status,/pause,/resume,/tick-now` | **删** |
| `app/modules/im_intake/service.py — process_one()` | **删** |
| `app/config.py` — `f4_enabled`, `f4_scan_interval_min`, `f4_batch_cap` | **删** |
| `app/config.py` — `f4_hard_max_asks`, `f4_pdf_timeout_hours`, `f4_soft_question_max` | **保留**（service 在用）|
| `app/adapters/boss/playwright_adapter.py` — daemon 专用方法 `list_chat_index`/`list_received_resumes` | **延迟评估**：如只被已删除路径引用则删，否则保留 |
| `tests/modules/im_intake/test_concurrent_lock.py` | **删** |
| `tests/modules/im_intake/test_scheduler_lock.py` | **删** |
| `tests/modules/im_intake/test_scheduler_disabled_by_default.py` | **删** |
| `tests/modules/im_intake/test_e2e_smoke.py` | **改**：去掉 scheduler 导入，测 /collect-chat 端到端 |
| `frontend/src/views/Intake.vue` — 顶部 `.control-bar` 调度器 UI | **删**（保留候选人列表 + 开始沟通）|
| `frontend/src/api/intake.js` — `getSchedulerStatus`, `pauseScheduler`, `resumeScheduler`, `tickNow` | **删** |

## 8. 配置

`.env` 变更：
```
# 删除
F4_ENABLED=
F4_SCAN_INTERVAL_MIN=
F4_BATCH_CAP=

# 保留
F4_HARD_MAX_ASKS=3
F4_PDF_TIMEOUT_HOURS=72
F4_SOFT_QUESTION_MAX=3
```

`chrome.storage.local` 新增：
- `intakeAutoScanEnabled: bool`（默认 false）
- `intakeAutoScanLastTickAt: number`（timestamp）

## 9. 测试策略

### 后端单测
- `tests/modules/im_intake/test_daily_cap.py` — GET /daily-cap 返回 used/max/remaining
- `tests/modules/im_intake/test_autoscan_rank.py` — /autoscan/rank 优先级排序逻辑
- `tests/modules/im_intake/test_autoscan_tick_stats.py` — POST /autoscan/tick-stats 写 audit
- `tests/modules/im_intake/test_audit_events_f4.py` — analyze_chat/record_asked/apply_terminal 各写对应 stage
- `tests/modules/im_intake/test_apply_terminal_transitions.py` — pending_human / abandoned / complete 三终态写对 audit + 改对 intake_status

### Extension / E2E
- 手动：popup 开关 → 自动扫描 10 min 周期 → 真实 chat/index 页面扫到 ≥ 1 候选人 → audit_events 出现 `F4_autoscan_tick` + `F4_candidate_enter`
- Playwright mock 跳过（不实装）

## 10. 里程碑

- T1: 删后端 F4 daemon + scheduler UI
- T2: F5→F3.1 改名（docs + 代码 + 测试）
- T3: F6→F3.2 改名（docs + 代码）
- T4: 后端 `/daily-cap`, `/autoscan/rank`, `/autoscan/tick-stats`
- T5: 后端 audit_events F4_* 写入
- T6: extension `intake_*` 改名
- T7: extension `background.js` chrome.alarms + popup 开关
- T8: extension `intake_autoScanTick`
- T9: 端到端 QA（真实 Boss 页面）+ 4xx/5xx 清单

## 11. 风险

| ID | 风险 | 缓解 |
|---|---|---|
| R1 | alarm 触发时 HR 浏览器不在 chat/index 页 | 只在目标 URL 的 tab 上 sendMessage；找不到目标 tab 静默跳过 |
| R2 | 连续点 geek-item 被 Boss 反检测 | 每人之间 3–8s 随机停顿；daily_cap 硬上限 |
| R3 | chat-conversation DOM 切换慢 | `intake_waitFor` 5s 超时 + 继续下一人 |
| R4 | 扫到大量无关已 complete 候选人 | 后端 /autoscan/rank 已过滤 complete/abandoned |
| R5 | audit_events 写失败 | 包在 try/except，失败只打日志不阻塞主流程 |

## 12. 不做的事

- 向新候选人主动打招呼（F3 干）
- 面邀 / 日程（F6 干，新 F6 = 原 F6，即 F3.2 之后的流程）
- IM 多轮深度对话
- 候选人撤回/拒绝意图识别（pending_human 兜底）
