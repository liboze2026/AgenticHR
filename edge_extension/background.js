// background.js — 招聘助手 Service Worker

const INTAKE_ALARM_NAME = "intake_autoscan";
const INTAKE_ALARM_PERIOD_MIN = 5;

const OUTBOX_ALARM_NAME = "intake_outbox_poll";
const OUTBOX_ALARM_PERIOD_MIN = 0.5;  // 30s; Chrome 120+ MV3 allows <1min

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({
      serverUrl: "http://127.0.0.1:8000",
      intake_autoscan_enabled: false,
    });
    console.log("招聘助手已安装，默认服务器地址: http://127.0.0.1:8000");
  }
  ensureAlarm();
  ensureOutboxAlarm();
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
  ensureOutboxAlarm();
});

async function ensureAlarm() {
  const { intake_autoscan_enabled } = await chrome.storage.local.get(["intake_autoscan_enabled"]);
  if (intake_autoscan_enabled) {
    const existing = await chrome.alarms.get(INTAKE_ALARM_NAME);
    if (!existing) {
      chrome.alarms.create(INTAKE_ALARM_NAME, { periodInMinutes: INTAKE_ALARM_PERIOD_MIN });
      console.log("[intake] auto-scan alarm created period=", INTAKE_ALARM_PERIOD_MIN, "min");
    }
  } else {
    await chrome.alarms.clear(INTAKE_ALARM_NAME);
  }
}

async function ensureOutboxAlarm() {
  const { intake_autoscan_enabled } = await chrome.storage.local.get(["intake_autoscan_enabled"]);
  if (!intake_autoscan_enabled) {
    await chrome.alarms.clear(OUTBOX_ALARM_NAME);
    return;
  }
  const existing = await chrome.alarms.get(OUTBOX_ALARM_NAME);
  if (!existing) {
    chrome.alarms.create(OUTBOX_ALARM_NAME, { periodInMinutes: OUTBOX_ALARM_PERIOD_MIN });
    console.log("[intake] outbox poll alarm created period=", OUTBOX_ALARM_PERIOD_MIN, "min");
  }
}

async function fetchIsRunning() {
  const { serverUrl, authToken } = await chrome.storage.local.get(["serverUrl", "authToken"]);
  if (!serverUrl || !authToken) return false;
  try {
    const r = await fetch(`${serverUrl}/api/intake/settings`, {
      headers: { "Authorization": `Bearer ${authToken}` },
    });
    if (!r.ok) return false;
    const s = await r.json();
    return !!s.is_running;
  } catch {
    return false;
  }
}

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
  } catch (e) {
    console.warn("[intake] outbox claim fetch failed:", e?.message || e);
    return;
  }
  if (!resp.ok) {
    console.warn("[intake] outbox claim HTTP", resp.status);
    return;
  }
  const data = await resp.json();
  const items = data.items || [];
  if (!items.length) return;

  const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
  if (!tabs.length) {
    for (const it of items) {
      await reportAck(it.id, false, "no Boss tab open");
    }
    return;
  }
  const preferred = tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0];
  for (const it of items) {
    try {
      await chrome.tabs.sendMessage(preferred.id, {
        type: "intake_outbox_dispatch",
        outbox: it,
      });
    } catch (e) {
      await reportAck(it.id, false, `dispatch failed: ${e?.message || e}`);
    }
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
  } catch (e) {
    console.warn("[intake] outbox ack failed:", e?.message || e);
  }
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "intake_autoscan_enabled" in changes) {
    ensureAlarm();
    ensureOutboxAlarm();
  }
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === INTAKE_ALARM_NAME) {
    if (!(await fetchIsRunning())) {
      console.log("[intake] autoscan tick skipped: backend is_running=false");
      return;
    }
    try {
      const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
      if (!tabs.length) {
        console.log("[intake] autoscan tick skipped: no Boss tab open");
        return;
      }
      const preferred = tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0];
      await chrome.tabs.sendMessage(preferred.id, { type: "intake_autoscan_tick", ts: Date.now() });
      console.log("[intake] autoscan tick sent to tab", preferred.id, preferred.url);
    } catch (e) {
      console.warn("[intake] autoscan tick failed:", e?.message || e);
    }
  } else if (alarm.name === OUTBOX_ALARM_NAME) {
    if (!(await fetchIsRunning())) {
      console.log("[intake] outbox poll skipped: backend is_running=false");
      return;
    }
    await pollOutboxOnce();
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "intake_outbox_ack") {
    reportAck(msg.outbox_id, msg.success, msg.error || "").finally(() =>
      sendResponse({ ok: true })
    );
    return true;  // async response
  }
});
