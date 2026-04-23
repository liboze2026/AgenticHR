# Edge Extension Popup Redesign — Design

Date: 2026-04-23
Target: `edge_extension/popup.html`, `edge_extension/popup.js`
Scope: UI-only restructure. No backend/content-script behavioral changes.

## Problem

Current popup piles 7 sections onto a 360px canvas with no visual hierarchy:
server URL, login, F4 single collect, F3 recruit, auto-greet, resume collect
(single + batch), pause, result log. Each section uses `section-title` +
1–2 buttons. Duplicate heading style + inconsistent spacing (16px/12px/0)
make it look noisy and every button feels equally important.

Users do not use all actions at once. They use exactly the subset that
matches the currently open Boss 直聘 tab.

## Goals

1. Make the action relevant to the current Boss page obvious.
2. Keep every existing action reachable — no functional regression.
3. Reduce visual noise: consistent spacing, icon + small label, one color
   language (primary/secondary/danger).
4. Preserve every existing DOM `id` so `popup.js` event wiring does not
   break.

## Non-Goals

- No changes to `content.js`, `background.js`, `f3_selectors.js`,
  `chat_scrape.js`, `styles.css` (injected page styles).
- No new features. No removed features.
- No backend API changes.

## Button Inventory (ordered by real user workflow)

| Button id | Function | Trigger page |
|---|---|---|
| `btnRecruitStart` | F3 auto-greet on 推荐牛人 page | `zhipin.com/web/chat/recommend` |
| `recruitJobSelect` / `editCap` | F3 pre-req: job + daily cap | F3 |
| `btnPause` | F3 pause/resume | F3 running |
| `btnCollectSingleChat` | F4 LLM slot extract current chat | `zhipin.com/web/chat` |
| `btnCollect` | Single resume detail page collect | resume detail page |
| `btnBatchCollect` | Batch collect resumes already obtained | 消息列表页 |
| `btnAutoGreet` | Batch send 求简历 on 新招呼 list | 消息列表 · 新招呼 |
| `serverUrl` + `btnTestConnection` | Backend URL config + health | any (low-freq) |
| `btnLogin` / `btnLogout` + user display | Auth | any (one-off) |

## Layout

```
┌─────────────────────────────────────┐
│ ● 招聘助手           张三 ▾   ⚙️    │  TopBar: dot + user pill + settings
├─────────────────────────────────────┤
│ 📍 当前页：推荐牛人                  │  Context strip (tab URL driven)
├─────────────────────────────────────┤
│ [primary card — matches current page]│  One highlighted card at a time
├─────────────────────────────────────┤
│ ▾ 其他操作 (N)                      │  Collapsed by default
│   • 聊天页 · F4 单人采集             │
│   • 详情页 · 采集当前简历            │
│   • 新招呼 · 自动求简历              │
│   • 消息列表 · 批量采集已求简历      │
├─────────────────────────────────────┤
│ ▸ 日志                              │  Collapsed; auto-expand on error
└─────────────────────────────────────┘
```

Settings panel (opened via ⚙️ — slides over main area, close = back):

```
服务器 URL  [_______________]  [测试]
账号       已登录：张三   [退出]
           ─ or ─
           用户名/密码/登录（当未登录时）
```

## Context Detection

Read `chrome.tabs.query({active:true, currentWindow:true})` URL on popup open.
Map to card:

| URL contains | Primary card |
|---|---|
| `/web/chat/recommend` | F3 推荐牛人 |
| `/web/chat` (non-recommend) | F4 单聊采集 |
| `zhipin.com` (others) | 消息列表组（求简历 + 批量采集）|
| anything else | 无 — 显示提示 "请在 Boss 直聘页面使用" |

All non-primary actions collapse into "其他操作" list. Clicking an item there
expands it inline (so the action still works on any page).

## Visual System

- Colors: primary `#00b38a`, danger `#ff4d4f`, neutral text `#333` / muted `#999`.
  Drop the orange/blue ad-hoc backgrounds on individual buttons.
- Typography: 13/600 card title, 12/400 body, 11/400 caption.
- Spacing grid: 8 / 12 / 16. All cards use 12px internal padding, 12px gap.
- Icons: unicode (📍 ⚙️ ▶ ⏸ ▾ ▸) — no new assets.

## Behavioral Preservation

All existing ids remain in the DOM:
`statusDot, statusText, serverUrl, btnTestConnection, btnCollect,
btnBatchCollect, resultArea, loginSection, userSection, displayUser,
loginUsername, loginPassword, btnLogin, btnLogout, btnAutoGreet,
btnCollectSingleChat, recruitJobSelect, usageUsed, usageCap, editCap,
btnRecruitStart, recruitStats, btnPause`.

All existing `addEventListener` calls in `popup.js` continue to resolve.
`chrome.storage.onChanged` listener behavior unchanged.

Result display still uses `showResult()` → `#resultArea`. If log is
collapsed and result type is `error` or non-empty, auto-expand it.

## popup.js Additions

Minimal, additive:

```js
// 1. Context strip
async function detectPageContext() { /* query tab, set strip text + primary */ }

// 2. Collapse helpers (no jQuery, <20 lines)
function toggleCollapsible(headerEl, bodyEl) { ... }

// 3. Settings panel open/close
function openSettings() { settingsPanel.classList.add('open'); }
function closeSettings() { settingsPanel.classList.remove('open'); }

// 4. Auto-expand log on error (hook into showResult)
```

No changes to `collectCurrentResume`, `batchCollectFromList`, `autoGreet`,
`startAutoRecruit`, `loadJobs`, `loadDailyUsage`, `doLogin`, `doLogout`.

## Testing

- Load unpacked extension, open popup on each of these pages:
  - `/web/chat/recommend` → F3 card highlighted
  - `/web/chat` → F4 card highlighted
  - `/web/chat` message list → batch card highlighted
  - `about:blank` → "请在 Boss 直聘页面使用" hint
- Verify each button still triggers its existing handler.
- Pause button appears only while F3 running (storage driven).
- Login → user pill shows → logout → pill replaced with login form in settings.
- Log stays collapsed for success; auto-expands on error.

## Risks

- Context detection false-negative on unknown Boss URL path → fallback shows
  all actions in "其他操作" fully expanded (safe default).
- Popup height grows when settings panel + log both open → set `max-height:
  600px` with `overflow-y: auto` on body.

## Out of Scope / Future

- Dark mode.
- i18n (locale = zh-CN only).
- Keyboard shortcuts.
