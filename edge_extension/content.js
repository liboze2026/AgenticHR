/**
 * 招聘助手 - Content Script
 * Boss 直聘 (zhipin.com/web/chat/index)
 *
 * 核心设计：每次切换候选人后，等待 name-box 和聊天消息区全部稳定后再操作。
 * PDF 下载前验证 PDF 卡片标题已更新，确保下载的是当前候选人的简历。
 */

const LOG = [];
let _paused = false;
let _stopped = false;
let _running = false;

function log(msg) { LOG.push(`[${new Date().toLocaleTimeString()}] ${msg}`); console.log('[招聘助手]', msg); }
async function waitIfPaused() { while (_paused && !_stopped) await sleep(300); if (_stopped) throw new Error('已停止'); }

function _setRunning(val) {
  _running = val;
  chrome.storage.local.set({ recruitRunning: val, recruitPaused: false });
}
function _setPaused(val) {
  _paused = val;
  chrome.storage.local.set({ recruitPaused: val });
}

// 点击页面任意位置暂停/继续（仅在运行中有效）
document.addEventListener('click', (e) => {
  if (!_running) return;
  // 忽略插件自己触发的点击（自动化操作）
  if (e.isTrusted && !e._fromPlugin) {
    if (!_paused) {
      _setPaused(true);
      log('用户点击页面，已暂停');
    }
  }
}, true);

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const h = {
    collectCurrentResume: () => collectSingle(message.serverUrl, message.authToken || ''),
    batchCollect: () => batchCollect(message.serverUrl, message.authToken || ''),
    autoGreet: () => autoGreet(),
    autoGreetRecommend: () => autoGreetRecommend({
      jobId: message.jobId,
      serverUrl: message.serverUrl,
      authToken: message.authToken || '',
    }),
  };
  if (h[message.action]) {
    h[message.action]().then(r => sendResponse(r)).catch(e => sendResponse({ success: false, message: e.message, log: LOG }));
    return true;
  }
  if (message.action === 'ping') {
    const onMessagePage = !!document.querySelector('.geek-item') || window.location.href.includes('/web/geek/chat')
    sendResponse({ ok: true, onMessagePage })
    return true
  }
  if (message.action === 'pause') { _setPaused(true); sendResponse({ success: true }); }
  else if (message.action === 'resume') { _setPaused(false); sendResponse({ success: true }); }
  else if (message.action === 'stop') { _stopped = true; _setPaused(false); _setRunning(false); sendResponse({ success: true }); }
  else if (message.action === 'getStatus') { sendResponse({ running: _running, paused: _paused }); }
  else if (message.action === 'switchTab') { switchToTab(message.tabName); sendResponse({ success: true }); }
  else sendResponse({ success: false, message: '未知操作' });
  return false;
});

// ════════════════════════════════════════════════════════════════════
// 批量采集
// ════════════════════════════════════════════════════════════════════

async function batchCollect(serverUrl, authToken = '') {
  LOG.length = 0; _paused = false; _stopped = false; _setRunning(true);
  const items = document.querySelectorAll('.geek-item');
  if (!items.length) return { success: false, message: '未找到候选人列表' };

  log(`共 ${items.length} 个候选人`);
  const results = [];
  let created = 0, updated = 0, failed = 0;

  // 记录"上一个候选人"的状态用于检测变化
  let prevName = '';
  let prevPdfTitle = '';

  for (let i = 0; i < items.length; i++) {
    await waitIfPaused();
    const item = items[i];
    const listName = item.querySelector('.geek-name')?.textContent?.trim() || '';
    if (!listName) continue;
    log(`\n── [${i+1}/${items.length}] ${listName} ──`);

    // ① 点击候选人
    item.click();

    // ② 等面板完全切换：name-box 必须变为当前候选人
    if (!await waitForNameBox(listName, 6000)) {
      log(`面板未切换，跳过`);
      results.push({ name: listName, status: 'skip' }); failed++; continue;
    }

    // ③ 等聊天消息区加载完成
    // 关键：不能只等固定时间，要等 PDF 卡片标题变化（说明消息区已更新）
    await waitForChatUpdate(prevPdfTitle, 4000);
    // 额外等一下确保稳定
    await sleep(500);

    // ④ 读取当前状态（从正确的 PDF 卡片获取标题）
    const pdfCardInfo = findPdfCard();
    const hasPdf = !!pdfCardInfo;
    const currentPdfTitle = pdfCardInfo?.card.querySelector('.message-card-top-title')?.textContent?.trim() || '';

    // ⑤ 提取页面信息
    const detail = extractDetail();
    detail.boss_id = item.getAttribute('data-id') || '';
    supplementFromPushText(detail, item);

    // 二次验证：name-box 仍然是当前候选人（防止异步更新覆盖）
    const nameNow = document.querySelector('.name-box')?.textContent?.trim() || '';
    if (nameNow !== listName) {
      log(`二次验证失败: name-box="${nameNow}", 期望="${listName}"`);
      results.push({ name: listName, status: 'name_mismatch' }); failed++; continue;
    }

    log(`信息: 手机=${detail.phone||'无'} 学历=${detail.education||'无'} PDF=${hasPdf?currentPdfTitle.substring(0,30):'无'}`);

    // ⑥ 下载 PDF
    let method = 'page_only';
    if (hasPdf && currentPdfTitle && serverUrl) {
      const pdfResult = await downloadPdf(detail, listName, serverUrl, authToken);
      if (pdfResult.ok) {
        method = 'pdf_uploaded';
        created++;
        prevPdfTitle = currentPdfTitle;
        prevName = listName;
        results.push({ name: listName, status: method });
        await sleep(1500);
        continue;
      }
      log('PDF下载失败，退回页面数据');
    }

    // 提交页面数据
    try {
      const resp = await submitPageData(detail, serverUrl, authToken);
      if (resp.ok) { created++; method = 'page_created'; }
      else { updated++; method = 'duplicate'; }
    } catch { failed++; method = 'error'; }

    prevPdfTitle = currentPdfTitle;
    prevName = listName;
    results.push({ name: listName, status: method });
    await sleep(800);
  }

  _setRunning(false);
  return { success: true, data: results, summary: { total: results.length, created, updated, failed }, log: LOG };
}

// ════════════════════════════════════════════════════════════════════
// 等待聊天消息区更新（PDF 标题变化 或 消息区内容变化）
// ════════════════════════════════════════════════════════════════════

async function waitForChatUpdate(prevPdfTitle, timeout) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const curPdf = findPdfCard();
    const currentTitle = curPdf?.card.querySelector('.message-card-top-title')?.textContent?.trim() || '';
    // 如果 PDF 标题变了（或上一个没有 PDF 而现在有了），说明消息区已更新
    if (currentTitle && currentTitle !== prevPdfTitle) {
      log(`消息区已更新 (PDF标题变化, ${((Date.now()-start)/1000).toFixed(1)}秒)`);
      return;
    }
    // 如果上一个有 PDF 但当前没有，也说明切换了
    if (prevPdfTitle && !findPdfCard()) {
      log(`消息区已更新 (PDF卡片消失, ${((Date.now()-start)/1000).toFixed(1)}秒)`);
      return;
    }
    await sleep(200);
  }
  // 超时也继续，靠后续的固定等待
  log(`消息区等待超时，继续 (prevPdf="${prevPdfTitle?.substring(0,20)||'无'}")`);
}

// ════════════════════════════════════════════════════════════════════
// 等待面板姓名
// ════════════════════════════════════════════════════════════════════

async function waitForNameBox(expected, timeout) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const name = document.querySelector('.name-box')?.textContent?.trim();
    if (name === expected) return true;
    await sleep(150);
  }
  const actual = document.querySelector('.name-box')?.textContent?.trim() || '(空)';
  log(`name-box: "${actual}", 期望: "${expected}"`);
  return actual === expected;
}

// ════════════════════════════════════════════════════════════════════
// 单个采集
// ════════════════════════════════════════════════════════════════════

async function collectSingle(serverUrl, authToken = '') {
  LOG.length = 0;
  if (document.querySelector('.conversation-no-data'))
    return { success: false, message: '未选中联系人' };

  const detail = extractDetail();
  detail.boss_id = document.querySelector('.geek-item.selected')?.getAttribute('data-id') || '';
  supplementFromPushText(detail, document.querySelector('.geek-item.selected'));
  if (!detail.name) return { success: false, message: '无法获取候选人姓名' };

  if (findPdfCard() && serverUrl) {
    const result = await downloadPdf(detail, detail.name, serverUrl, authToken);
    if (result.ok) return { success: true, data: result.data, method: 'pdf_uploaded', log: LOG };
  }

  const resp = await submitPageData(detail, serverUrl, authToken);
  if (resp.ok) return { success: true, data: await resp.json(), method: 'page_only', log: LOG };
  return { success: true, data: detail, method: 'page_only', log: LOG };
}

// ════════════════════════════════════════════════════════════════════
// PDF 下载（带验证）
// ════════════════════════════════════════════════════════════════════

async function downloadPdf(candidateInfo, expectedName, serverUrl, authToken = '') {
  try {
    // 1. 下载前再次确认 name-box 是当前候选人
    const nameNow = document.querySelector('.name-box')?.textContent?.trim() || '';
    if (nameNow !== expectedName) {
      log(`PDF下载前验证失败: name-box="${nameNow}", 期望="${expectedName}"`);
      return { ok: false };
    }

    // 2. 关闭残留预览，然后强制删除所有 PDF iframe（确保干净状态）
    await closeDialog();
    await sleep(500);
    document.querySelectorAll('.attachment-iframe, iframe[src*="pdf"], iframe[src*="wflow"]').forEach(el => {
      log('删除残留iframe');
      el.remove();
    });
    await sleep(300);

    // 3. 确认页面上没有 PDF iframe 了
    if (document.querySelector('.attachment-iframe, iframe[src*="pdf"], iframe[src*="wflow"]')) {
      log('无法清除旧iframe，跳过');
      return { ok: false };
    }

    // 4. 找到真正的简历 PDF 卡片（跳过"同意附件"等系统卡片）
    const pdfInfo = findPdfCard();
    if (!pdfInfo) { log('未找到简历PDF卡片'); return { ok: false }; }
    const btn = pdfInfo.btn;
    log('点击预览...');
    btn.click();

    // 5. 等待全新的 iframe 出现（之前的已删除，新出现的一定是当前候选人的）
    let iframe = null;
    const t0 = Date.now();
    while (Date.now() - t0 < 10000) {
      await sleep(400);
      iframe = document.querySelector('.attachment-iframe, iframe[src*="pdf"], iframe[src*="wflow"]');
      if (iframe && (iframe.getAttribute('src') || '').length > 30) break;
      iframe = null;
    }
    if (!iframe) {
      log(`iframe超时 (${((Date.now()-t0)/1000).toFixed(1)}秒)`);
      await closeDialog();
      return { ok: false };
    }
    log(`新iframe出现 (${((Date.now()-t0)/1000).toFixed(1)}秒)`);

    // 6. 第三次确认 name-box
    const nameAfter = document.querySelector('.name-box')?.textContent?.trim() || '';
    if (nameAfter !== expectedName) {
      log(`预览后验证失败: "${nameAfter}" != "${expectedName}"`);
      await closeDialog();
      return { ok: false };
    }

    // 7. 提取 PDF URL
    const src = iframe.getAttribute('src') || '';
    const pdfUrl = extractPdfUrl(src);
    if (!pdfUrl) { log('无法提取URL'); await closeDialog(); return { ok: false }; }
    log(`URL: ${pdfUrl.substring(0, 60)}...`);

    // 8. 关闭预览
    await closeDialog();
    await sleep(400);

    // 8. 下载
    const fullUrl = pdfUrl.startsWith('http') ? pdfUrl : `https://www.zhipin.com${pdfUrl}`;
    const resp = await fetch(fullUrl, { credentials: 'include' });
    if (!resp.ok) { log(`下载失败: ${resp.status}`); return { ok: false }; }

    const blob = await resp.blob();
    log(`${blob.size} bytes`);
    if (blob.size < 1024) { log('文件太小'); return { ok: false }; }

    // 9. 上传
    const form = new FormData();
    let fileName = candidateInfo.pdf_filename || `${candidateInfo.name}.pdf`;
    if (!fileName.toLowerCase().endsWith('.pdf')) fileName += '.pdf';
    form.append('file', blob, fileName);
    form.append('candidate_name', candidateInfo.name || '');
    form.append('candidate_phone', candidateInfo.phone || '');
    form.append('candidate_email', candidateInfo.email || '');
    form.append('candidate_education', candidateInfo.education || '');
    form.append('candidate_work_years', String(candidateInfo.work_years || 0));
    form.append('candidate_job', candidateInfo.job_intention || '');

    const uploadHeaders = authToken ? { 'Authorization': `Bearer ${authToken}` } : {};
    const uploadResp = await fetch(`${serverUrl}/api/resumes/upload`, { method: 'POST', headers: uploadHeaders, body: form });
    if (uploadResp.ok) { log('上传成功'); return { ok: true, data: await uploadResp.json() }; }
    log(`上传失败: ${uploadResp.status}`);
    return { ok: false };
  } catch (e) {
    log(`异常: ${e.message}`);
    await closeDialog();
    return { ok: false };
  }
}

function extractPdfUrl(iframeSrc) {
  try { const u = new URL(iframeSrc, 'https://www.zhipin.com'); const p = u.searchParams.get('url'); if (p) return p; } catch {}
  const m = iframeSrc.match(/url=([^&]+)/); return m ? decodeURIComponent(m[1]) : null;
}

async function closeDialog() {
  // 尝试所有可能的关闭按钮
  const selectors = [
    '.resume-custom-close',
    '.resume-common-dialog .boss-popup__close',
    '.boss-popup__close',
    '.dialog-resume-full .close',
    '.icon-close',
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (btn && btn.offsetParent !== null) { // offsetParent !== null 表示可见
      btn.click();
      log(`关闭弹窗: ${sel}`);
      break;
    }
  }
  // 等弹窗消失
  await sleep(300);
  // 如果 iframe 还在，再点一次
  if (document.querySelector('.attachment-iframe')) {
    for (const sel of selectors) {
      const btn = document.querySelector(sel);
      if (btn && btn.offsetParent !== null) { btn.click(); break; }
    }
    await sleep(300);
  }
  // 最后手段：按 Escape
  if (document.querySelector('.attachment-iframe')) {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
    await sleep(300);
  }
}

// ════════════════════════════════════════════════════════════════════
// 数据提取
// ════════════════════════════════════════════════════════════════════

function extractDetail() {
  const name = document.querySelector('.name-box')?.textContent?.trim() || '';
  let age = '', workYearsRaw = '', education = '';
  const box = document.querySelector('.base-info-single-detial');
  if (box) box.querySelectorAll(':scope > div').forEach(div => {
    if (div.classList.contains('active-time') || div.classList.contains('name-contet')) return;
    const t = div.textContent.trim(); if (!t) return;
    if (t.includes('岁')) age = t;
    else if (/博士|硕士|研究生|本科|学士|大专|专科|高中|中专|MBA/.test(t) && !t.includes('年')) education = t;
    else if (t.includes('应届') || t.includes('经验') || /^\d+年/.test(t)) workYearsRaw = t;
    else if (!age && /\d/.test(t)) age = t;
  });

  const job = document.querySelector('.position-content .position-name')?.textContent?.trim()
    || document.querySelector('.geek-item.selected .source-job')?.textContent?.trim() || '';
  const chatText = document.querySelector('.chat-message-list')?.textContent || '';
  const pdfCardResult = findPdfCard();
  const pdfTitle = pdfCardResult?.card.querySelector('.message-card-top-title')?.textContent?.trim() || '';
  const allText = chatText + ' ' + pdfTitle;

  return {
    name, phone: (allText.match(/1[3-9]\d{9}/)||[])[0] || '',
    email: (allText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/)||[])[0] || '',
    education: normEdu(education), work_years: parseYr(workYearsRaw), job_intention: job,
    skills: '', source: 'boss_zhipin', pdf_filename: pdfTitle,
    work_experience: Array.from(document.querySelectorAll('.experience-content.detail-list .work-content .value')).map(el => el.textContent.trim()).join('\n'),
    raw_text: `年龄:${age} 工作:${workYearsRaw} 学历:${education} PDF:${pdfTitle}`,
  };
}

function supplementFromPushText(d, item) {
  if (!item) return;
  const msg = item.querySelector('.push-text')?.textContent?.trim() || '';
  if (!d.phone) { const m = msg.match(/1[3-9]\d{9}/); if (m) d.phone = m[0]; }
  if (!d.email) { const m = msg.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/); if (m) d.email = m[0]; }
}

async function submitPageData(d, url, authToken = '') {
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  return fetch(`${url}/api/resumes/`, { method: 'POST', headers,
    body: JSON.stringify({ name: d.name, phone: d.phone||'', email: d.email||'', education: d.education||'',
      work_years: d.work_years||0, job_intention: d.job_intention||'', skills: '', work_experience: d.work_experience||'',
      source: 'boss_zhipin', raw_text: d.raw_text||'' }) });
}

// ════════════════════════════════════════════════════════════════════
// 自动打招呼
// ════════════════════════════════════════════════════════════════════

async function autoGreet() {
  LOG.length = 0; _paused = false; _stopped = false; _setRunning(true);
  if (!switchToTab('新招呼')) return { success: false, message: '未找到"新招呼"标签' };
  await sleep(1500);
  const items = document.querySelectorAll('.geek-item');
  if (!items.length) return { success: false, message: '新招呼列表为空' };

  log(`${items.length} 个新招呼`);
  const results = []; let greeted = 0, skipped = 0;
  for (let i = 0; i < items.length; i++) {
    await waitIfPaused();
    const name = items[i].querySelector('.geek-name')?.textContent?.trim() || `#${i+1}`;
    items[i].click(); await sleep(1500);
    if (!await waitForSel('.chat-conversation', 3000)) { skipped++; results.push({ name, status: 'skipped' }); continue; }
    await sleep(500);
    let ok = false;
    for (const btn of document.querySelectorAll('.operate-btn')) {
      if (btn.textContent.trim().includes('求简历')) {
        btn.click(); await sleep(800);
        const c = document.querySelector('.exchange-tooltip .boss-btn-primary'); if (c) { c.click(); await sleep(500); }
        ok = true; greeted++; results.push({ name, status: 'greeted' }); break;
      }
    }
    if (!ok) { skipped++; results.push({ name, status: 'skipped', reason: '无求简历按钮' }); }
    await sleep(2000 + Math.random() * 3000);
  }
  _setRunning(false);
  return { success: true, data: results, summary: { total: results.length, greeted, skipped, failed: 0 }, log: LOG };
}

// ════════════════════════════════════════════════════════════════════
// 工具
// ════════════════════════════════════════════════════════════════════

function findPdfCard() {
  // Find the real resume PDF card: last boss-green card with non-disabled card-btn
  const cards = document.querySelectorAll('.message-card-wrap.boss-green');
  for (let i = cards.length - 1; i >= 0; i--) {
    const btn = cards[i].querySelector('.card-btn:not(.disabled)');
    if (btn) return { card: cards[i], btn };
  }
  return null;
}

function switchToTab(n) {
  const t = document.querySelector(`.chat-label-item[title*="${n}"]`);
  if (t) { t.click(); return true; }
  for (const el of document.querySelectorAll('.chat-label-item'))
    if ((el.querySelector('.content')?.textContent||'').includes(n)) { el.click(); return true; }
  return false;
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function waitForSel(sel, timeout = 3000) {
  return new Promise(resolve => {
    if (document.querySelector(sel)) { resolve(true); return; }
    const s = Date.now();
    const iv = setInterval(() => { if (document.querySelector(sel) || Date.now()-s > timeout) { clearInterval(iv); resolve(!!document.querySelector(sel)); } }, 100);
  });
}
function parseYr(t) { if (!t) return 0; if (t.includes('应届')) return 0; const m = t.match(/(\d+)\s*年/); return m ? parseInt(m[1]) : 0; }
function normEdu(t) { if (!t) return ''; for (const [k,v] of Object.entries({'博士':'博士','硕士':'硕士','研究生':'硕士','本科':'本科','学士':'本科','大专':'大专','专科':'大专'})) if (t.includes(k)) return v; return t; }

// ════════════════════════════════════════════════════════════════════
// F3 工具 — 反检测人类式操作 (spec §7.2, §7.3)
// ════════════════════════════════════════════════════════════════════

/**
 * 人类式点击: scrollIntoView + mouseover → mousedown → mouseup → click
 * spec §7.2 反检测要求. 不直接 .click() 因为 isTrusted=false 更易被检出.
 */
async function simulateHumanClick(el) {
  if (!el) throw new Error('simulateHumanClick: element is null');
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  await sleep(300);

  const opts = { bubbles: true, cancelable: true, view: window, button: 0 };
  el.dispatchEvent(new MouseEvent('mouseover', opts));
  await sleep(150 + Math.random() * 100);
  el.dispatchEvent(new MouseEvent('mousedown', opts));
  await sleep(50 + Math.random() * 50);
  el.dispatchEvent(new MouseEvent('mouseup', opts));
  el.dispatchEvent(new MouseEvent('click', opts));
}

/**
 * 取推荐牛人 iframe 的 contentDocument. 推荐页结构:
 *   top frame: /web/chat/recommend (空壳)
 *   iframe[src*=/web/frame/recommend/]: 真正的卡片 + 岗位下拉所在处
 * 2026-04-21 live 探查证实.
 */
function _getRecommendDoc() {
  for (const f of document.querySelectorAll('iframe')) {
    try {
      const src = f.src || '';
      if (!src.includes(F3_SELECTORS.RECOMMEND_IFRAME_PATH)) continue;
      const doc = f.contentDocument;
      if (doc && doc.body) return doc;
    } catch (_) { /* cross-origin fallback */ }
  }
  // 回退: 任一 same-origin 且含 '打招呼' 文本的 iframe
  for (const f of document.querySelectorAll('iframe')) {
    try {
      const doc = f.contentDocument;
      if (doc && doc.body && doc.body.innerText.includes('打招呼')) return doc;
    } catch (_) {}
  }
  return null;
}

/**
 * 检测风控告警. 命中返 true + halt 主循环.
 * spec §7.3. 扫描 top frame 和推荐 iframe 两个 document.
 */
function detectRiskControl() {
  const riskSelectors = [
    F3_SELECTORS.RISK_CAPTCHA,
    F3_SELECTORS.RISK_VERIFY,
    F3_SELECTORS.RISK_ALERT,
    F3_SELECTORS.PAID_GREET_DIALOG,
  ];
  const docs = [document];
  const iframeDoc = _getRecommendDoc();
  if (iframeDoc) docs.push(iframeDoc);

  for (const doc of docs) {
    for (const sel of riskSelectors) {
      try {
        const el = doc.querySelector(sel);
        if (el && el.offsetParent !== null) {
          return { detected: true, source: `selector:${sel}` };
        }
      } catch (_) {}
    }
    const bodyText = doc.body?.innerText || '';
    for (const pattern of F3_SELECTORS.RISK_TEXT_PATTERNS) {
      if (bodyText.includes(pattern)) {
        return { detected: true, source: `text:${pattern}` };
      }
    }
  }
  return { detected: false };
}

/**
 * 从 Boss 推荐牛人 list 卡片抠字段. LIST-only (spec §5.2).
 * 返回 ScrapedCandidate-shaped plain object 或 null (信号 scrape 失败).
 */
function scrapeRecommendCard(cardEl) {
  if (!cardEl) return null;

  // boss_id 在 .card-inner 上 (2026-04-21 live 校准)
  const innerEl = cardEl.querySelector(F3_SELECTORS.CARD_INNER) || cardEl;
  const bossId = innerEl.getAttribute('data-id')
    || cardEl.getAttribute('data-id')
    || '';
  if (!bossId) return null;

  const name = cardEl.querySelector(F3_SELECTORS.CARD_NAME)?.textContent?.trim() || '';
  if (!name) return null;

  // base-info: "22岁 27年应届生 硕士 刚刚活跃"
  const baseText = (cardEl.querySelector(F3_SELECTORS.CARD_BASE_INFO)?.textContent || '')
    .replace(/\s+/g, ' ').trim();
  const age = parseInt(baseText.match(/(\d+)岁/)?.[1] || '', 10) || null;
  const gradMatch = baseText.match(/(\d{2})年(应届生|毕业)/);
  const gradYear = gradMatch ? (2000 + parseInt(gradMatch[1], 10)) : null;
  const eduMatch = baseText.match(/博士|硕士|研究生|本科|学士|大专|专科|高中|中专|MBA/);
  const education = normEdu(eduMatch?.[0] || '');
  const activeStatus =
    (baseText.match(/刚刚活跃|今日活跃|在线|\d+日内活跃|\d+小时前活跃/) || [''])[0];

  // expect-wrap .content: "北京 全栈工程师" — 空格分 (无 · 分隔). 末 token 视为岗位.
  const focusText = (cardEl.querySelector(F3_SELECTORS.CARD_RECENT_FOCUS)?.textContent || '')
    .replace(/\s+/g, ' ').trim();
  const focusTokens = focusText.split(' ').filter(Boolean);
  const intendedJob = focusTokens.length > 0 ? focusTokens[focusTokens.length - 1] : '';

  // edu-wrap .content: "北京交通大学 软件工程 硕士" — 空格分 (首=学校 / 中=专业 / 末=学位)
  const eduRow = (cardEl.querySelector(F3_SELECTORS.CARD_EDUCATION_ROW)?.textContent || '')
    .replace(/\s+/g, ' ').trim();
  const eduParts = eduRow.split(' ').filter(Boolean);
  const school = eduParts[0] || '';
  const major = eduParts.length >= 3 ? eduParts[1] : (eduParts.length === 2 ? '' : (eduParts[1] || ''));

  // col-3 工作经历: 有则 timeline-wrap 里 "2024.09 2024.11 公司 岗位"; 无则显示 "未填写工作经历"
  const timelineEl = cardEl.querySelector(F3_SELECTORS.CARD_WORK_ROW_TIMELINE);
  const col3Text = (cardEl.querySelector(F3_SELECTORS.CARD_WORK_ROW)?.textContent || '')
    .replace(/\s+/g, ' ').trim();
  const latestWorkBrief = timelineEl
    ? (timelineEl.textContent || '').replace(/\s+/g, ' ').trim()
    : (col3Text === '未填写工作经历' ? '' : col3Text);

  const workYears = parseWorkYearsFromBrief(latestWorkBrief);

  const tagEls = cardEl.querySelectorAll(F3_SELECTORS.CARD_TAG_ITEM);
  const skill_tags = [];
  const school_tier_tags = [];
  const ranking_tags = [];
  let recommendation_reason = '';
  tagEls.forEach(t => {
    const txt = t.textContent.trim();
    if (!txt) return;
    // .tag-item.highlight = 推荐理由 (live 校准)
    if (t.classList?.contains('highlight') || /来自相似职位|推荐理由/.test(txt)) {
      recommendation_reason = txt;
    } else if (/^\d+院校$|^985$|^211$|^双一流$/.test(txt)) {
      school_tier_tags.push(txt);
    } else if (/专业前\d+%/.test(txt)) {
      ranking_tags.push(txt);
    } else {
      skill_tags.push(txt);
    }
  });

  const expected_salary = cardEl.querySelector(F3_SELECTORS.CARD_SALARY)?.textContent?.trim() || '';

  return {
    name, boss_id: bossId,
    age, education, grad_year: gradYear, work_years: workYears,
    school, major, intended_job: intendedJob,
    skill_tags, school_tier_tags, ranking_tags,
    expected_salary, active_status: activeStatus,
    recommendation_reason,
    latest_work_brief: latestWorkBrief,
    raw_text: '',
    boss_current_job_title: getBossTopJobTitle(),
  };
}

function parseWorkYearsFromBrief(brief) {
  if (!brief || brief === '未填写工作经历') return 0;
  // 两种格式: "2024.09 - 2024.11 公司 岗位" (带 hyphen) 或 "2024.09 2024.11 公司 岗位" (无 hyphen)
  const m = brief.match(/(\d{4})\.(\d{1,2})\s*-?\s*(\d{4})\.(\d{1,2})/);
  if (m) {
    const start = parseInt(m[1], 10) * 12 + parseInt(m[2], 10);
    const end = parseInt(m[3], 10) * 12 + parseInt(m[4], 10);
    return Math.max(0, Math.round((end - start) / 12));
  }
  return 0;
}

function getBossTopJobTitle() {
  // 岗位下拉在 iframe 里 (2026-04-21 live 校准), 非 top frame
  const doc = _getRecommendDoc() || document;
  const el = doc.querySelector(F3_SELECTORS.TOP_JOB_TEXT);
  if (!el) return '';
  const full = (el.textContent || '').replace(/\s+/g, ' ').trim();
  // "全栈工程师 _ 北京  400-500元/天" → 取 _ 前
  return full.split('_')[0].split('(')[0].trim();
}

// ════════════════════════════════════════════════════════════════════
// F3 主循环 — autoGreetRecommend
// ════════════════════════════════════════════════════════════════════

async function autoGreetRecommend({ jobId, serverUrl, authToken }) {
  LOG.length = 0; _paused = false; _stopped = false; _setRunning(true);
  const stats = { total: 0, greeted: 0, skipped: 0, rejected: 0, failed: 0, blocked: false };
  _setStats(stats);

  try {
    if (!location.pathname.includes(F3_SELECTORS.PAGE_URL_PATH)) {
      return { success: false, message: '请先打开 Boss 推荐牛人页', log: LOG };
    }

    // 岗位对齐检查 (Q8 B)
    const jobResp = await fetch(`${serverUrl}/api/screening/jobs/${jobId}`, {
      headers: { 'Authorization': `Bearer ${authToken}` },
    });
    if (!jobResp.ok) {
      return { success: false, message: `加载岗位失败: HTTP ${jobResp.status}`, log: LOG };
    }
    const sysJob = await jobResp.json();
    const bossJobName = getBossTopJobTitle();
    const sim = stringSimilarity(sysJob.title || '', bossJobName || '');
    if (sim < 0.7 && bossJobName) {
      const ok = confirm(
        `岗位可能不匹配:\n  Boss 页: ${bossJobName}\n  系统选的: ${sysJob.title}\n继续?`
      );
      if (!ok) { _setRunning(false); return { success: false, message: '用户取消', log: LOG }; }
    }

    let idx = 0;
    const processedBossIds = new Set();
    let silentMissCount = 0;

    while (!_stopped) {
      await waitIfPaused();

      const risk = detectRiskControl();
      if (risk.detected) {
        stats.blocked = true;
        log(`风控命中: ${risk.source}`);
        _setRunning(false);
        return {
          success: false,
          message: `检测到 Boss 风控，已自动停止 (${risk.source})`,
          summary: stats, log: LOG,
        };
      }

      // 卡片全在 iframe 里 (2026-04-21 live 校准)
      const recDoc = _getRecommendDoc();
      if (!recDoc) {
        _setRunning(false);
        return { success: false, message: '未找到推荐牛人 iframe, 请刷新页面', summary: stats, log: LOG };
      }
      const cards = Array.from(recDoc.querySelectorAll(F3_SELECTORS.CARD_ITEM));
      if (idx >= cards.length) {
        // 滚动在 iframe 的 scroll 容器里, 不是 top window
        const scrollable = recDoc.querySelector('.list-body') || recDoc.scrollingElement || recDoc.body;
        scrollable.scrollTop = scrollable.scrollHeight;
        await sleep(2000);
        const newCards = Array.from(recDoc.querySelectorAll(F3_SELECTORS.CARD_ITEM));
        if (newCards.length === cards.length) {
          log(`列表到底. 处理完 ${idx} 人`);
          break;
        }
        continue;
      }

      const card = cards[idx];
      idx++;

      const scraped = scrapeRecommendCard(card);
      if (!scraped) { stats.skipped++; _setStats(stats); continue; }
      if (processedBossIds.has(scraped.boss_id)) { stats.skipped++; _setStats(stats); continue; }
      processedBossIds.add(scraped.boss_id);

      stats.total++;
      log(`[${idx}] ${scraped.name} (${scraped.boss_id.substring(0,12)})`);

      let decision;
      try {
        const evalResp = await fetch(`${serverUrl}/api/recruit/evaluate_and_record`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`,
          },
          body: JSON.stringify({ job_id: jobId, candidate: scraped }),
        });
        if (evalResp.status === 401) {
          _setRunning(false);
          return { success: false, message: '登录已过期', summary: stats, log: LOG };
        }
        if (!evalResp.ok) {
          log(`后端错 HTTP ${evalResp.status}, 跳过`);
          stats.failed++; _setStats(stats); continue;
        }
        decision = await evalResp.json();
      } catch (e) {
        log(`网络错: ${e.message}, 跳过`);
        stats.failed++; _setStats(stats); continue;
      }

      if (decision.decision === 'blocked_daily_cap') {
        stats.blocked = true;
        log(`每日配额已满: ${decision.reason}`);
        _setRunning(false);
        return {
          success: false, message: `今日配额已满 (${decision.reason})`,
          summary: stats, log: LOG,
        };
      }
      if (decision.decision === 'error_no_competency') {
        _setRunning(false);
        return {
          success: false, message: `岗位能力模型未生成`,
          summary: stats, log: LOG,
        };
      }
      if (decision.decision === 'skipped_already_greeted') {
        stats.skipped++; log('历史已打过招呼，跳过');
        _setStats(stats);
      } else if (decision.decision === 'rejected_low_score') {
        stats.rejected++;
        log(`分 ${decision.score} < 阈值 ${decision.threshold}, 跳过`);
        _setStats(stats);
      } else if (decision.decision === 'error_scoring') {
        stats.failed++;
        log(`打分异常: ${decision.reason}, 跳过`);
        _setStats(stats);
      } else if (decision.decision === 'should_greet') {
        const greetBtn = findGreetButtonInCard(card);
        if (!greetBtn) {
          log('打招呼按钮找不到, 记失败');
          await reportGreetResult(serverUrl, authToken, decision.resume_id, false, 'button_not_found');
          stats.failed++; _setStats(stats); continue;
        }
        try {
          await simulateHumanClick(greetBtn);
          await sleep(1000 + Math.random() * 500);
          const btnText = greetBtn.textContent.trim();
          const done = greetBtn.classList.contains('done')
                    || btnText.includes('已打招呼')
                    || card.querySelector(F3_SELECTORS.CARD_GREET_BTN_DONE);
          if (done) {
            await reportGreetResult(serverUrl, authToken, decision.resume_id, true, '');
            stats.greeted++; log('打招呼成功');
            silentMissCount = 0;
          } else {
            await reportGreetResult(serverUrl, authToken, decision.resume_id, false, 'button_no_response');
            stats.failed++; silentMissCount++;
            log(`按钮无反应 (silent miss ${silentMissCount}/3)`);
            if (silentMissCount >= 3) {
              _setRunning(false);
              return {
                success: false, message: '连续 3 次按钮无反应, 熔断',
                summary: stats, log: LOG,
              };
            }
          }
        } catch (e) {
          log(`点击异常: ${e.message}`);
          await reportGreetResult(serverUrl, authToken, decision.resume_id, false, e.message);
          stats.failed++;
        }
        _setStats(stats);
      }

      // 节流
      const delay = 2000 + Math.random() * 3000;
      await sleep(delay);
      if (stats.greeted > 0 && stats.greeted % 10 === 0) {
        const longPause = 3000 + Math.random() * 3000;
        log(`已打 ${stats.greeted}, 长停 ${Math.round(longPause/1000)}s`);
        await sleep(longPause);
      }
    }

    _setRunning(false);
    return { success: true, summary: stats, log: LOG };
  } catch (e) {
    _setRunning(false);
    return { success: false, message: `异常: ${e.message}`, summary: stats, log: LOG };
  }
}

async function reportGreetResult(serverUrl, authToken, resumeId, success, errorMsg) {
  try {
    await fetch(`${serverUrl}/api/recruit/record-greet`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${authToken}`,
      },
      body: JSON.stringify({ resume_id: resumeId, success, error_msg: errorMsg }),
    });
  } catch (e) {
    log(`record-greet 上报失败: ${e.message}`);
  }
}

function _setStats(stats) {
  chrome.storage.local.set({ recruitStats: stats });
}

function stringSimilarity(a, b) {
  if (!a || !b) return 0;
  // Chinese-friendly: use character bigrams + unigrams, compute Jaccard
  const tokens = s => {
    const set = new Set();
    const t = s.trim().toLowerCase();
    if (t.length === 0) return set;
    if (t.length === 1) { set.add(t); return set; }
    for (let i = 0; i < t.length - 1; i++) {
      set.add(t.slice(i, i + 2));  // bigram
    }
    for (const ch of t) set.add(ch);  // unigram for robustness
    return set;
  };
  const A = tokens(a), B = tokens(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const t of A) if (B.has(t)) inter++;
  const union = A.size + B.size - inter;
  return union === 0 ? 0 : inter / union;
}

/**
 * 在 card 里找"打招呼"按钮. 2026-04-21 live 校准: 选择器 "button.btn.btn-greet" valid.
 * 保留 textContent fallback 防未来 DOM 变.
 */
function findGreetButtonInCard(card) {
  const primary = card.querySelector(F3_SELECTORS.CARD_GREET_BTN);
  if (primary && primary.offsetParent !== null) return primary;

  // fallback: 扫 button/.btn-greet 任一含 "打招呼" 文本且可见
  const btns = card.querySelectorAll('button, [role="button"], .btn-greet');
  for (const b of btns) {
    if ((b.textContent || '').includes('打招呼') && b.offsetParent !== null) {
      return b;
    }
  }
  return null;
}

// ---- F5: chat page automation helpers ----
// Selectors are PLACEHOLDERS; verify on live page.

async function f5_typeAndSendChatMessage(text) {
  const input = document.querySelector(".chat-input textarea, .chat-input [contenteditable=true]");
  if (!input) return { ok: false, reason: "输入框未找到" };
  input.focus();
  if (input.tagName === "TEXTAREA") {
    input.value = "";
    for (const ch of text) {
      input.value += ch;
      input.dispatchEvent(new InputEvent("input", { bubbles: true, data: ch }));
      await new Promise((r) => setTimeout(r, 20 + Math.random() * 60));
    }
  } else {
    input.textContent = text;
    input.dispatchEvent(new InputEvent("input", { bubbles: true }));
  }
  await new Promise((r) => setTimeout(r, 200 + Math.random() * 300));
  const sendBtn = document.querySelector(
    ".chat-input .send-btn, button[data-action=send], .chat-action-send"
  );
  if (!sendBtn) return { ok: false, reason: "发送按钮未找到" };
  if (typeof simulateHumanClick === "function") {
    await simulateHumanClick(sendBtn);
  } else {
    sendBtn.click();
  }
  return { ok: true };
}

async function f5_clickRequestResumeButton() {
  const btn = Array.from(document.querySelectorAll("button, a")).find(
    (el) => /求简历|索要简历/.test(el.textContent || "")
  );
  if (!btn) return { ok: false, reason: "求简历按钮未找到" };
  if (typeof simulateHumanClick === "function") {
    await simulateHumanClick(btn);
  } else {
    btn.click();
  }
  return { ok: true };
}

async function f5_checkPdfReceived(bossId) {
  const attachRows = document.querySelectorAll(".msg-row.attachment, .attachment-card");
  for (const el of attachRows) {
    const fromId = el.getAttribute("data-sender");
    if (fromId === bossId) {
      const link = el.querySelector("a[href*='.pdf'], a[download]");
      if (link) return { present: true, url: link.href };
    }
  }
  return { present: false };
}

window.f5_typeAndSendChatMessage = f5_typeAndSendChatMessage;
window.f5_clickRequestResumeButton = f5_clickRequestResumeButton;
window.f5_checkPdfReceived = f5_checkPdfReceived;
