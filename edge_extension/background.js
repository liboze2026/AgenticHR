// background.js — 招聘助手 Service Worker (双阶段重构 2026-04-26)
//
// Step1（每小时）：扫 BOSS 全部列表 → 注册新候选人
// Step2（每3小时）：逐个打开聊天 → LLM分析 → 发消息
// 互斥：chrome.storage.local.phase_running 标志
// 关闭浏览器 = phase_running 自动清除 = 系统停止

const STEP1_ALARM = "intake_step1_scan";
const STEP1_PERIOD_MIN = 60;

const STEP2_ALARM = "intake_step2_enrich";
const STEP2_PERIOD_MIN = 180;

const OUTBOX_ALARM_NAME = "intake_outbox_poll";
const OUTBOX_ALARM_PERIOD_MIN = 0.5; // 30s

// ── 安装/启动 ──────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({
      serverUrl: "http://127.0.0.1:8000",
      intake_enabled: false,
    });
    console.log("[招聘助手] 已安装，默认服务器: http://127.0.0.1:8000");
  }
  ensureAlarms();
});

chrome.runtime.onStartup.addListener(() => {
  // 浏览器重启时清除残留的 phase_running 标志
  chrome.storage.local.remove("phase_running");
  ensureAlarms();
});

// ── Alarm 管理 ─────────────────────────────────────────────────
async function ensureAlarms() {
  const { intake_enabled } = await chrome.storage.local.get(["intake_enabled"]);
  // 先全清，再按需重建（防止 period 改变时旧alarm残留）
  await chrome.alarms.clearAll();
  if (!intake_enabled) {
    console.log("[alarm] intake_enabled=false，所有alarm已清除");
    return;
  }
  chrome.alarms.create(STEP1_ALARM, { periodInMinutes: STEP1_PERIOD_MIN });
  chrome.alarms.create(STEP2_ALARM, { periodInMinutes: STEP2_PERIOD_MIN });
  chrome.alarms.create(OUTBOX_ALARM_NAME, { periodInMinutes: OUTBOX_ALARM_PERIOD_MIN });
  console.log("[alarm] Step1=", STEP1_PERIOD_MIN, "min / Step2=", STEP2_PERIOD_MIN,
              "min / Outbox=", OUTBOX_ALARM_PERIOD_MIN, "min");
}

// intake_enabled 变更时重建 alarm
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "intake_enabled" in changes) {
    ensureAlarms();
  }
});

// ── 互斥锁 ────────────────────────────────────────────────────
async function acquirePhase(phase) {
  const { phase_running } = await chrome.storage.local.get(["phase_running"]);
  if (phase_running && phase_running !== phase) {
    console.log(`[mutex] ${phase} 被 ${phase_running} 阻塞`);
    return false;
  }
  await chrome.storage.local.set({ phase_running: phase });
  return true;
}

async function releasePhase() {
  await chrome.storage.local.remove("phase_running");
}

// ── BOSS tab 查找 ─────────────────────────────────────────────
async function getBossTab() {
  const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
  if (!tabs.length) return null;
  return (
    tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0]
  );
}

// ── Outbox poll（发消息，沿用原机制）──────────────────────────
async function pollOutboxOnce() {
  const { serverUrl, authToken } = await chrome.storage.local.get([
    "serverUrl",
    "authToken",
  ]);
  if (!serverUrl || !authToken) return;

  let resp;
  try {
    resp = await fetch(`${serverUrl}/api/intake/outbox/claim`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ limit: 1 }),
    });
  } catch (e) {
    console.warn("[outbox] claim fetch 失败:", e?.message || e);
    return;
  }
  if (!resp.ok) {
    console.warn("[outbox] claim HTTP", resp.status);
    return;
  }
  const data = await resp.json();
  const items = data.items || [];
  if (!items.length) return;

  const tab = await getBossTab();
  if (!tab) {
    for (const it of items) await reportAck(it.id, false, "no Boss tab open");
    return;
  }
  for (const it of items) {
    try {
      await chrome.tabs.sendMessage(tab.id, {
        type: "intake_outbox_dispatch",
        outbox: it,
      });
    } catch (e) {
      await reportAck(it.id, false, `dispatch failed: ${e?.message || e}`);
    }
  }
}

async function reportAck(outboxId, success, error = "") {
  const { serverUrl, authToken } = await chrome.storage.local.get([
    "serverUrl",
    "authToken",
  ]);
  if (!serverUrl || !authToken) return;
  try {
    await fetch(`${serverUrl}/api/intake/outbox/${outboxId}/ack`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ success, error }),
    });
  } catch (e) {
    console.warn("[outbox] ack 失败:", e?.message || e);
  }
}

// ── Step1 / Step2 运行器 ──────────────────────────────────────
async function runStep1() {
  if (!(await acquirePhase("step1"))) return;
  try {
    const tab = await getBossTab();
    if (!tab) {
      console.log("[step1] 无 BOSS 标签页，跳过");
      return;
    }
    console.log("[step1] 发送 intake_step1_scan → tab", tab.id);
    try {
      const result = await chrome.tabs.sendMessage(tab.id, {
        type: "intake_step1_scan",
      });
      console.log("[step1] 完成:", result);
    } catch (e) {
      console.warn("[step1] sendMessage 失败:", e?.message || e);
    }
  } finally {
    await releasePhase();
  }
}

async function runStep2() {
  if (!(await acquirePhase("step2"))) return;
  try {
    const tab = await getBossTab();
    if (!tab) {
      console.log("[step2] 无 BOSS 标签页，跳过");
      return;
    }
    console.log("[step2] 发送 intake_step2_enrich → tab", tab.id);
    try {
      const result = await chrome.tabs.sendMessage(tab.id, {
        type: "intake_step2_enrich",
      });
      console.log("[step2] 完成:", result);
    } catch (e) {
      console.warn("[step2] sendMessage 失败:", e?.message || e);
    }
  } finally {
    await releasePhase();
  }
}

// ── Alarm 分发 ────────────────────────────────────────────────
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === STEP1_ALARM) {
    await runStep1();
  } else if (alarm.name === STEP2_ALARM) {
    await runStep2();
  } else if (alarm.name === OUTBOX_ALARM_NAME) {
    // Step 运行期间暂停 outbox poll，防止 DOM 抢占
    const { phase_running } = await chrome.storage.local.get(["phase_running"]);
    if (!phase_running) {
      await pollOutboxOnce();
    }
  }
});

// ── 消息监听 ──────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // outbox ack 回调（从 content script）
  if (msg?.type === "intake_outbox_ack") {
    reportAck(msg.outbox_id, msg.success, msg.error || "").finally(() =>
      sendResponse({ ok: true })
    );
    return true;
  }

  // 手动触发 Step1（来自 popup 或前端）
  if (msg?.type === "manual_step1") {
    runStep1().then(() => sendResponse({ ok: true }));
    return true;
  }

  // 手动触发 Step2（来自 popup 或前端）
  if (msg?.type === "manual_step2") {
    runStep2().then(() => sendResponse({ ok: true }));
    return true;
  }

  // 查询当前 phase 状态（来自 popup）
  if (msg?.type === "get_phase_status") {
    chrome.storage.local.get(["phase_running", "intake_enabled"]).then((s) => {
      sendResponse({
        phase_running: s.phase_running || null,
        intake_enabled: s.intake_enabled || false,
      });
    });
    return true;
  }
});
