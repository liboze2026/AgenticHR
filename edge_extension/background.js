// background.js — 招聘助手 Service Worker

const INTAKE_ALARM_NAME = "intake_autoscan";
const INTAKE_ALARM_PERIOD_MIN = 5;

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({
      serverUrl: "http://127.0.0.1:8000",
      intake_autoscan_enabled: false,
    });
    console.log("招聘助手已安装，默认服务器地址: http://127.0.0.1:8000");
  }
  ensureAlarm();
});

chrome.runtime.onStartup.addListener(ensureAlarm);

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

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "intake_autoscan_enabled" in changes) {
    ensureAlarm();
  }
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== INTAKE_ALARM_NAME) return;
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
});
