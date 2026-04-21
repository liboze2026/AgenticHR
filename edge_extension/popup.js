// popup.js — 招聘助手弹出窗口逻辑

const DEFAULT_SERVER_URL = "http://127.0.0.1:8000";

const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const serverUrlInput = document.getElementById("serverUrl");
const btnTestConnection = document.getElementById("btnTestConnection");
const btnCollect = document.getElementById("btnCollect");
const btnBatchCollect = document.getElementById("btnBatchCollect");
const resultArea = document.getElementById("resultArea");
const loginSection = document.getElementById("loginSection");
const userSection = document.getElementById("userSection");
const displayUser = document.getElementById("displayUser");

// ── Initialization ──────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  await loadServerUrl();
  await loadAuthToken();
  await checkConnection();
  updateAuthUI();

  document.getElementById("btnLogin").addEventListener("click", doLogin);
  document.getElementById("btnLogout").addEventListener("click", doLogout);
});

// ── Server URL persistence ──────────────────────────────────────────

async function loadServerUrl() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["serverUrl"], (result) => {
      serverUrlInput.value = result.serverUrl || DEFAULT_SERVER_URL;
      resolve();
    });
  });
}

function saveServerUrl() {
  const url = serverUrlInput.value.trim() || DEFAULT_SERVER_URL;
  chrome.storage.local.set({ serverUrl: url });
  return url;
}

function getServerUrl() {
  return serverUrlInput.value.trim() || DEFAULT_SERVER_URL;
}

// ── Auth token persistence ──────────────────────────────────────────

let _authToken = '';
let _authUser = '';

async function loadAuthToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["authToken", "authUser"], (result) => {
      _authToken = result.authToken || '';
      _authUser = result.authUser || '';
      resolve();
    });
  });
}

function getAuthToken() {
  return _authToken;
}

function updateAuthUI() {
  if (_authToken) {
    loginSection.style.display = 'none';
    userSection.style.display = 'block';
    displayUser.textContent = _authUser || '用户';
  } else {
    loginSection.style.display = 'block';
    userSection.style.display = 'none';
  }
}

async function doLogin() {
  const url = getServerUrl();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  if (!username || !password) { showResult("请输入用户名和密码", "error"); return; }

  try {
    const resp = await fetch(`${url}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await resp.json();
    if (!resp.ok) { showResult(data.detail || "登录失败", "error"); return; }
    _authToken = data.token;
    _authUser = data.user?.display_name || data.user?.username || username;
    chrome.storage.local.set({ authToken: _authToken, authUser: _authUser });
    updateAuthUI();
    showResult("登录成功", "success");
  } catch {
    showResult("无法连接服务器", "error");
  }
}

function doLogout() {
  _authToken = '';
  _authUser = '';
  chrome.storage.local.remove(["authToken", "authUser"]);
  updateAuthUI();
  showResult("已退出登录", "");
}

// ── Connection check ────────────────────────────────────────────────

async function checkConnection() {
  const url = getServerUrl();
  setStatus("checking");
  showResult("正在检测连接...", "");

  try {
    const resp = await fetch(`${url}/api/health`, {
      signal: AbortSignal.timeout(5000),
    });
    if (resp.ok) {
      setStatus("connected");
      showResult("已连接到招聘助手后端", "success");
      document.querySelectorAll('button').forEach(btn => {
        if (btn.id !== 'check-connection') {
          btn.disabled = false;
          btn.style.opacity = '';
        }
      });
    } else {
      setStatus("error");
      showResult(`连接失败: HTTP ${resp.status}`, "error");
      document.querySelectorAll('button').forEach(btn => {
        if (btn.id !== 'check-connection') {
          btn.disabled = true;
          btn.style.opacity = '0.5';
        }
      });
    }
  } catch (err) {
    setStatus("error");
    showResult(`无法连接到服务器: ${err.message}\n请确认后端服务已启动`, "error");
    document.querySelectorAll('button').forEach(btn => {
      if (btn.id !== 'check-connection') {
        btn.disabled = true;
        btn.style.opacity = '0.5';
      }
    });
  }
}

// ── Collect current resume ──────────────────────────────────────────

async function collectCurrentResume() {
  const url = saveServerUrl();
  const token = getAuthToken();
  showResult("正在采集当前候选人信息...", "");
  setButtonsDisabled(true);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.includes("zhipin.com")) {
      showResult("请在Boss直聘页面上使用此功能", "error");
      setButtonsDisabled(false);
      return;
    }

    const response = await chrome.tabs.sendMessage(tab.id, {
      action: "collectCurrentResume",
      serverUrl: url,
      authToken: token,
    });

    if (!response?.success) {
      showResult(`采集失败: ${response?.message || "无响应，请刷新页面重试"}`, "error");
      setButtonsDisabled(false);
      return;
    }

    const d = response.data;
    const method = response.method || "page_only";

    // 构建调试日志
    const logLines = response.log?.length ? ['\n--- 调试日志 ---', ...response.log] : [];

    if (method === "pdf_uploaded") {
      showResult(
        [`采集成功 (PDF已解析)`, `姓名: ${d.name}`, `手机: ${d.phone}`, `邮箱: ${d.email}`, `学历: ${d.education}`, ...logLines].join('\n'),
        "success"
      );
    } else {
      // 页面信息提交
      const postResp = await fetch(`${url}/api/resumes/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { "Authorization": `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          name: d.name || "", phone: d.phone || "", email: d.email || "",
          education: d.education || "", work_years: d.work_years || 0,
          job_intention: d.job_intention || "", skills: d.skills || "",
          work_experience: d.work_experience || "", source: "boss_zhipin",
          raw_text: d.raw_text || "",
        }),
      });
      if (postResp.ok) {
        const result = await postResp.json();
        showResult(
          [`采集成功 (仅页面信息)`, `姓名: ${result.name}`, `手机: ${result.phone}`, `邮箱: ${result.email}`, `学历: ${result.education}`, ...logLines].join('\n'),
          "success"
        );
      } else {
        showResult([`提交失败: HTTP ${postResp.status}`, ...logLines].join('\n'), "error");
      }
    }
  } catch (err) {
    showResult(`操作失败: ${err.message}`, "error");
  } finally {
    setButtonsDisabled(false);
  }
}

// ── Batch collect from list ─────────────────────────────────────────

async function batchCollectFromList() {
  const url = saveServerUrl();
  const token = getAuthToken();

  // Pre-flight: ping the content script to verify page readiness
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.includes("zhipin.com")) {
      showResult("请在Boss直聘页面上使用此功能", "error");
      return;
    }

    let pingResp;
    try {
      pingResp = await chrome.tabs.sendMessage(tab.id, { action: "ping" });
    } catch (e) {
      showResult("请先刷新Boss直聘页面（插件需要页面刷新后才能工作）", "error");
      return;
    }
    if (chrome.runtime.lastError || !pingResp) {
      showResult("请先刷新Boss直聘页面（插件需要页面刷新后才能工作）", "error");
      return;
    }
    if (!pingResp.onMessagePage) {
      showResult("请先打开Boss直聘的「消息」页面再进行批量采集", "error");
      return;
    }
  } catch (err) {
    showResult("请先刷新Boss直聘页面（插件需要页面刷新后才能工作）", "error");
    return;
  }

  showResult("正在逐个采集候选人详细信息并下载PDF简历...\n请勿操作Boss直聘页面！", "");
  setButtonsDisabled(true);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    const response = await chrome.tabs.sendMessage(tab.id, {
      action: "batchCollect",
      serverUrl: url,
      authToken: token,
    });

    if (!response?.success) {
      showResult(`采集失败: ${response?.message || "无响应，请刷新页面重试"}`, "error");
      setButtonsDisabled(false);
      return;
    }

    const summary = response.summary || {};
    const results = response.data || [];

    // Categorized counts
    const withPdf = results.filter(r => r.status === 'pdf_uploaded').length;
    const pageOnly = results.filter(r => r.status === 'page_created' || r.status === 'page_only' || r.status === 'duplicate').length;
    const failedCount = results.filter(r => ['skip', 'name_mismatch', 'error'].includes(r.status)).length;
    const missingContact = results.filter(r => r.noPhone && r.noEmail).length;

    const lines = [
      `批量采集完成`,
      `总计: ${summary.total || results.length} 人`,
      `PDF简历: ${withPdf} 人`,
      `仅页面信息: ${pageOnly} 人`,
      `失败/跳过: ${failedCount} 人`,
      ...(missingContact > 0 ? [`缺少联系方式（无手机且无邮箱）: ${missingContact} 人`] : []),
      ``,
      `详情:`,
    ];
    results.forEach(r => {
      const label = r.status === 'pdf_uploaded' ? 'PDF已上传解析'
        : r.status === 'page_created' ? '页面信息已新增'
        : r.status === 'duplicate' ? '已存在(更新)'
        : r.status === 'page_only' ? '仅页面信息'
        : r.status;
      lines.push(`  ${r.name}: ${label}`);
    });

    // 显示调试日志
    if (response.log && response.log.length > 0) {
      lines.push('', '--- 调试日志 ---');
      response.log.forEach(l => lines.push(l));
    }
    showResult(lines.join("\n"), summary.failed === 0 ? "success" : "error");
  } catch (err) {
    showResult(`操作失败: ${err.message}`, "error");
  } finally {
    setButtonsDisabled(false);
  }
}

// ── UI Helpers ──────────────────────────────────────────────────────

function setStatus(state) {
  statusDot.className = "status-dot";
  switch (state) {
    case "connected": statusDot.classList.add("connected"); statusText.textContent = "已连接"; break;
    case "error": statusDot.classList.add("error"); statusText.textContent = "连接失败"; break;
    case "checking": statusText.textContent = "检测中..."; break;
    default: statusText.textContent = "未连接";
  }
}

function showResult(message, type) {
  resultArea.textContent = message;
  resultArea.className = "result-area";
  if (type) resultArea.classList.add(type);
}

const btnPause = document.getElementById("btnPause");
let isPaused = false;
let isRunning = false;

// 恢复上次状态（popup 关闭再打开时）
chrome.storage.local.get(["recruitRunning", "recruitPaused"], (data) => {
  isRunning = !!data.recruitRunning;
  isPaused = !!data.recruitPaused;
  updatePauseButton();
});

// 监听 storage 变化（content.js 修改状态时实时更新）
chrome.storage.onChanged.addListener((changes) => {
  if (changes.recruitRunning) {
    isRunning = !!changes.recruitRunning.newValue;
    updatePauseButton();
  }
  if (changes.recruitPaused) {
    isPaused = !!changes.recruitPaused.newValue;
    updatePauseButton();
  }
});

function updatePauseButton() {
  if (isRunning) {
    btnPause.style.display = "block";
    if (isPaused) {
      btnPause.textContent = "继续（点击页面也可暂停）";
      btnPause.style.background = "#52c41a";
    } else {
      btnPause.textContent = "暂停";
      btnPause.style.background = "#ff4d4f";
    }
  } else {
    btnPause.style.display = "none";
  }
}

function setButtonsDisabled(disabled) {
  btnCollect.disabled = disabled;
  btnBatchCollect.disabled = disabled;
  btnTestConnection.disabled = disabled;
  btnAutoGreet.disabled = disabled;
  btnRecruitStart.disabled = disabled;

  if (disabled) {
    isRunning = true;
    isPaused = false;
    updatePauseButton();
  }
  // 不在这里隐藏按钮，让 storage 监听来控制
}

async function sendToContent(action) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) return chrome.tabs.sendMessage(tab.id, { action });
}

btnPause.addEventListener("click", async () => {
  if (!isRunning) return;

  if (!isPaused) {
    await sendToContent("pause");
    isPaused = true;
  } else {
    await sendToContent("resume");
    isPaused = false;
  }
  updatePauseButton();
});

// ── Auto Greet ──────────────────────────────────────────────────────

const btnAutoGreet = document.getElementById("btnAutoGreet");

async function autoGreet() {
  showResult("正在自动打招呼，请勿操作Boss直聘页面...\n将逐个点击候选人并发送求简历请求", "");
  setButtonsDisabled(true);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.includes("zhipin.com")) {
      showResult("请在Boss直聘页面上使用此功能", "error");
      setButtonsDisabled(false);
      return;
    }

    const response = await chrome.tabs.sendMessage(tab.id, { action: "autoGreet" });

    if (!response?.success) {
      showResult(`打招呼失败: ${response?.message || "无响应，请刷新页面重试"}`, "error");
      setButtonsDisabled(false);
      return;
    }

    const summary = response.summary || {};
    const results = response.data || [];
    const lines = [
      `自动打招呼完成`,
      `总计: ${summary.total || results.length} 人`,
      `已求简历: ${summary.greeted || 0}`,
      `跳过: ${summary.skipped || 0}`,
      `失败: ${summary.failed || 0}`,
      ``,
      `详情:`,
    ];
    results.forEach(r => {
      const statusText = r.status === 'greeted' ? '已求简历' : `跳过(${r.reason || ''})`;
      lines.push(`  ${r.name}: ${statusText}`);
    });

    if (response.log?.length) {
      lines.push('', '--- 调试日志 ---');
      response.log.forEach(l => lines.push(l));
    }
    showResult(lines.join("\n"), summary.failed === 0 ? "success" : "error");
  } catch (err) {
    showResult(`操作失败: ${err.message}`, "error");
  } finally {
    setButtonsDisabled(false);
  }
}

// ── Event Listeners ─────────────────────────────────────────────────

btnTestConnection.addEventListener("click", () => { saveServerUrl(); checkConnection(); });
btnAutoGreet.addEventListener("click", autoGreet);
btnCollect.addEventListener("click", collectCurrentResume);
btnBatchCollect.addEventListener("click", batchCollectFromList);
serverUrlInput.addEventListener("change", saveServerUrl);
// authToken is now managed via login/logout, no manual input needed

// ── F3 Recruit ──────────────────────────────────────────────────────

const recruitJobSelect = document.getElementById('recruitJobSelect');
const usageUsed = document.getElementById('usageUsed');
const usageCap = document.getElementById('usageCap');
const editCap = document.getElementById('editCap');
const btnRecruitStart = document.getElementById('btnRecruitStart');
const recruitStats = document.getElementById('recruitStats');

async function loadJobs() {
  const url = getServerUrl();
  const token = getAuthToken();
  if (!token) return;
  try {
    const r = await fetch(`${url}/api/screening/jobs?active_only=true`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return;
    const data = await r.json();
    recruitJobSelect.innerHTML = '<option value="">-- 选择岗位 --</option>';
    const jobs = Array.isArray(data) ? data : (data.items || []);
    jobs.forEach(j => {
      if (j.competency_model_status !== 'approved') return;
      const opt = document.createElement('option');
      opt.value = j.id;
      opt.textContent = `${j.title} (阈值 ${j.greet_threshold || 60})`;
      recruitJobSelect.appendChild(opt);
    });
  } catch (e) {
    console.error('loadJobs fail', e);
  }
}

async function loadDailyUsage() {
  const url = getServerUrl();
  const token = getAuthToken();
  if (!token) return;
  try {
    const r = await fetch(`${url}/api/recruit/daily-usage`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return;
    const d = await r.json();
    usageUsed.textContent = d.used;
    usageCap.textContent = d.cap;
  } catch (e) {
    console.error('loadDailyUsage fail', e);
  }
}

async function editDailyCap() {
  const url = getServerUrl();
  const token = getAuthToken();
  const newCap = prompt('输入新的每日配额 (0-10000)', usageCap.textContent);
  if (newCap === null) return;
  const n = parseInt(newCap, 10);
  if (!(n >= 0 && n <= 10000)) {
    showResult('配额必须 0-10000', 'error'); return;
  }
  try {
    const r = await fetch(`${url}/api/recruit/daily-cap`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ cap: n }),
    });
    if (r.ok) { await loadDailyUsage(); showResult(`配额已改为 ${n}`, 'success'); }
    else { showResult(`修改失败: HTTP ${r.status}`, 'error'); }
  } catch (e) {
    showResult(`网络错: ${e.message}`, 'error');
  }
}

async function startAutoRecruit() {
  const url = getServerUrl();
  const token = getAuthToken();
  if (!token) { showResult('请先登录', 'error'); return; }
  const jobId = parseInt(recruitJobSelect.value, 10);
  if (!jobId) { showResult('请选择岗位', 'error'); return; }

  recruitStats.textContent = '';
  showResult('F3 自动打招呼已启动，请勿操作 Boss 推荐牛人页...', '');
  setButtonsDisabled(true);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.includes('zhipin.com/web/chat/recommend')) {
      showResult('请先打开 Boss 推荐牛人页', 'error');
      setButtonsDisabled(false); return;
    }

    const resp = await chrome.tabs.sendMessage(tab.id, {
      action: 'autoGreetRecommend',
      jobId, serverUrl: url, authToken: token,
    });

    if (resp?.success) {
      const s = resp.summary;
      showResult(
        [
          'F3 自动打招呼完成',
          `总 ${s.total} 人: 打招呼 ${s.greeted}, 跳过 ${s.skipped}, 淘汰 ${s.rejected}, 失败 ${s.failed}`,
        ].join('\n'),
        'success'
      );
    } else {
      const s = resp?.summary;
      showResult(
        [
          resp?.message || '未知错误',
          s ? `进度: 总 ${s.total}, 成 ${s.greeted}, 淘 ${s.rejected}, 失 ${s.failed}` : '',
        ].filter(Boolean).join('\n'),
        'error'
      );
    }
    await loadDailyUsage();
  } catch (e) {
    showResult(`异常: ${e.message}`, 'error');
  } finally {
    setButtonsDisabled(false);
  }
}

chrome.storage.onChanged.addListener((changes) => {
  if (changes.recruitStats) {
    const s = changes.recruitStats.newValue || {};
    if (s.total !== undefined) {
      recruitStats.textContent = `进度: 总 ${s.total}, 成 ${s.greeted||0}, 淘 ${s.rejected||0}, 跳 ${s.skipped||0}, 失 ${s.failed||0}`;
    }
  }
});

document.addEventListener('DOMContentLoaded', async () => {
  await loadJobs();
  await loadDailyUsage();
});

editCap.addEventListener('click', (e) => { e.preventDefault(); editDailyCap(); });
btnRecruitStart.addEventListener('click', startAutoRecruit);
