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

// ── 安装/启动 ──────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({
      serverUrl: "http://127.0.0.1:8000",
      intake_enabled: false,
    });
    console.log("[招聘助手] 已安装，默认服务器: http://127.0.0.1:8000");
  }
  // 安装/更新/重新加载扩展时清残留锁，避免上一次 SW 崩在 phase_running=true
  chrome.storage.local.remove(["phase_running", "phase_started_at"]);
  ensureAlarms();
});

chrome.runtime.onStartup.addListener(() => {
  // 浏览器重启时清除残留的 phase_running 标志
  chrome.storage.local.remove(["phase_running", "phase_started_at"]);
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
  console.log("[alarm] Step1=", STEP1_PERIOD_MIN, "min / Step2=", STEP2_PERIOD_MIN, "min");
}

// intake_enabled 变更时重建 alarm
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "intake_enabled" in changes) {
    ensureAlarms();
  }
});

// ── 互斥锁 ────────────────────────────────────────────────────
const PHASE_LOCK_TIMEOUT_MS = 30 * 60 * 1000; // SW 崩溃后 30 分钟自动失效

async function acquirePhase(phase) {
  const { phase_running, phase_started_at } = await chrome.storage.local.get([
    "phase_running",
    "phase_started_at",
  ]);
  const stale =
    phase_running &&
    phase_started_at &&
    Date.now() - phase_started_at > PHASE_LOCK_TIMEOUT_MS;
  if (stale) {
    console.warn(`[mutex] ${phase_running} 锁超时（${Math.round((Date.now() - phase_started_at) / 60000)}min），强制清锁`);
  }
  if (phase_running && phase_running !== phase && !stale) {
    console.log(`[mutex] ${phase} 被 ${phase_running} 阻塞`);
    return false;
  }
  await chrome.storage.local.set({ phase_running: phase, phase_started_at: Date.now() });
  return true;
}

async function releasePhase() {
  await chrome.storage.local.remove(["phase_running", "phase_started_at"]);
}

// ── BOSS tab 查找 ─────────────────────────────────────────────
async function getBossTab() {
  const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
  if (!tabs.length) return null;
  return (
    tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0]
  );
}

// ── Step1 / Step2 运行器 ──────────────────────────────────────
async function runStep1() {
  if (!(await acquirePhase("step1"))) return { skipped: "mutex" };
  try {
    const tab = await getBossTab();
    if (!tab) {
      console.log("[step1] 无 BOSS 标签页，跳过");
      return { ok: false, reason: "no_boss_tab" };
    }
    console.log("[step1] 发送 intake_step1_scan → tab", tab.id);
    try {
      const result = await chrome.tabs.sendMessage(tab.id, {
        type: "intake_step1_scan",
      });
      console.log("[step1] 完成:", result);
      return result;
    } catch (e) {
      console.warn("[step1] sendMessage 失败:", e?.message || e);
      return { ok: false, reason: e?.message || String(e) };
    }
  } finally {
    await releasePhase();
  }
}

async function runStep2() {
  if (!(await acquirePhase("step2"))) return { skipped: "mutex" };
  try {
    const tab = await getBossTab();
    if (!tab) {
      console.log("[step2] 无 BOSS 标签页，跳过");
      return { ok: false, reason: "no_boss_tab" };
    }
    console.log("[step2] 发送 intake_step2_enrich → tab", tab.id);
    try {
      const result = await chrome.tabs.sendMessage(tab.id, {
        type: "intake_step2_enrich",
      });
      console.log("[step2] 完成:", result);
      return result;
    } catch (e) {
      console.warn("[step2] sendMessage 失败:", e?.message || e);
      return { ok: false, reason: e?.message || String(e) };
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
  }
});

// ── 消息监听 ──────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // 手动触发 Step1（来自 popup 或前端）
  if (msg?.type === "manual_step1") {
    console.log("[bg] manual_step1 received");
    runStep1()
      .then((r) => { console.log("[bg] manual_step1 done:", r); sendResponse(r || { ok: true }); })
      .catch((e) => { console.error("[bg] manual_step1 err:", e); sendResponse({ ok: false, error: String(e?.message || e) }); });
    return true;
  }

  // 手动触发 Step2（来自 popup 或前端）
  if (msg?.type === "manual_step2") {
    console.log("[bg] manual_step2 received");
    runStep2()
      .then((r) => { console.log("[bg] manual_step2 done:", r); sendResponse(r || { ok: true }); })
      .catch((e) => { console.error("[bg] manual_step2 err:", e); sendResponse({ ok: false, error: String(e?.message || e) }); });
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

  // 强制清残留 phase 锁 + 关自动化（来自 popup 紧急按钮）
  if (msg?.type === "intake_force_reset") {
    Promise.all([
      chrome.storage.local.remove(["phase_running", "phase_started_at"]),
      chrome.storage.local.set({ intake_enabled: false }),
      chrome.alarms.clearAll(),
    ]).then(() => {
      console.log("[bg] intake_force_reset done");
      sendResponse({ ok: true });
    }).catch((e) => sendResponse({ ok: false, error: String(e?.message || e) }));
    return true;
  }
});
