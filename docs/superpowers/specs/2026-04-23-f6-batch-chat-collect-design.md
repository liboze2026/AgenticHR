# F6: 批量聊天候选人采集 — 设计文档

**Date**: 2026-04-23
**Phase**: M3 F6（项目内部编号，接续 F5 手动 intake）
**Scope**: 扩展新按钮 + 后端 2 个改动 + 前端岗位设置

---

## 1. 背景

F5 实现了单人手动 intake（扩展逐个触发）。现需要批量从 Boss 直聘消息列表页（`/web/chat/index`）采集 X 个新候选人，并按岗位配置的学校层次/学历标准过滤。

已有可复用基础：
- `batchCollect(serverUrl, authToken)` in `content.js`：点击遍历 `.geek-item`、等面板切换、提取信息、下载 PDF
- `extractDetail()`：从右侧面板提取学历（本科/硕士等）
- `scrapeRecommendCard()` + `school_tier_tags` 解析：F3 已有 985/211 tag 识别逻辑
- `upsert_resume_by_boss_id`：recruit_bot 模块，按 `(user_id, boss_id)` 去重 upsert
- `recruitJobSelect`：popup.js 已有岗位下拉，可直接复用

---

## 2. 目标与非目标

### Goals
- G1: 在 popup 中选岗位 + 设置数量 X → 自动从消息列表批量采集符合标准的新候选人
- G2: 过滤已在简历库中的候选人（按 boss_id 去重，提前跳过，减少无效点击）
- G3: 过滤不符合学校层次 / 最低学历的候选人
- G4: 每个岗位独立配置批量采集标准（学校层次 + 最低学历）
- G5: 采集结果仅入简历库（source=`batch_chat`），不触发 intake 流程

### Non-goals
- 不新增候选人来源渠道（仍是已有消息列表，不主动搜索新候选人）
- 不触发 intake / 打招呼 / 评分等后续流程
- 不支持暂停/继续（现有 batchCollect 有暂停，此次不复用，保持简单）

---

## 3. 整体架构

```
popup.html          popup.js                content.js               后端
─────────────────────────────────────────────────────────────────────────
[岗位下拉] ──→ loadJobs() (已有)
[数量 X  ]
[开始按钮] ──→ batchCollectNewFromList()
                  ├→ GET /api/jobs/{jobId}   → 取 batch_collect_criteria
                  ├→ sendMessage(batchCollectNew, {jobId, limit, criteria})
                  │       ↓
                  │  batchCollectNew(limit, criteria, serverUrl, authToken)
                  │   ①  读 .geek-item[data-id] → boss_ids[]
                  │   ②  POST /api/resumes/check-boss-ids → existing Set
                  │   ③  逐项过滤 + 点击 + 提取 + 检查标准
                  │   ④  合格 → submitPageData / downloadPdf (source=batch_chat)
                  │   ⑤  collected >= limit → break
                  └← {collected, skipped_dup, skipped_criteria, failed}
```

---

## 4. 后端改动

### 4.1 Job 模型扩展

文件：`app/modules/screening/models.py`

```python
batch_collect_criteria = Column(JSON, nullable=True)
```

JSON 结构（默认 null = 不限制）：

```json
{
  "school_tiers": ["985", "211"],
  "education_min": "本科"
}
```

- `school_tiers`：空列表 `[]` = 不限学校；可选值：`"985"`、`"211"`、`"双一流"`
- `education_min`：`null` = 不限；可选值：`"大专"` `"本科"` `"硕士"` `"博士"`

### 4.2 Alembic 迁移

新建 `migrations/versions/0016_job_batch_collect_criteria.py`：

```python
op.add_column('jobs', sa.Column('batch_collect_criteria', sa.JSON(), nullable=True))
```

无 downgrade 数据损失（JSON 列 nullable，drop 即可）。

### 4.3 Schema 扩展

文件：`app/modules/screening/schemas.py`

在 `JobCreate` / `JobUpdate` / `JobResponse` 中加：
```python
batch_collect_criteria: dict | None = None
```

现有 `PATCH /api/jobs/{id}` 端点无需改动，schema 扩展即可接受新字段。

### 4.4 新端点：check-boss-ids

文件：`app/modules/resume/router.py`

```
POST /api/resumes/check-boss-ids
Request:  { "boss_ids": ["xxx", "yyy", ...] }
Response: { "existing": ["xxx"] }
```

实现：`db.query(Resume.boss_id).filter(Resume.boss_id.in_(boss_ids), Resume.user_id == user_id).all()`

返回已在库中的 boss_id 列表，扩展据此跳过对应候选人。

---

## 5. Extension 改动

### 5.1 popup.html

在消息列表操作区域追加：

```html
<div id="cardBatchCollectNew" class="section">
  <div class="section-title">批量采集新候选人</div>
  <div style="display:flex;gap:8px;align-items:center;">
    <select id="batchNewJobSelect"></select>
    <input id="batchNewLimit" type="number" min="1" max="50" value="10" style="width:60px;">
    <button id="btnBatchCollectNew">开始采集</button>
  </div>
</div>
```

`batchNewJobSelect` 与 `recruitJobSelect` 共享同一 `loadJobs()` 调用填充选项。

### 5.2 popup.js

新函数 `batchCollectNewFromList()`（参照 `batchCollectFromList` 结构）：

1. 校验页面（需在消息列表页）
2. 取 jobId 和 limit
3. `GET /api/jobs/{jobId}` → 取 `batch_collect_criteria`
4. `chrome.tabs.sendMessage({action:'batchCollectNew', limit, criteria, serverUrl, authToken})`
5. 结果：展示 `采集成功 N 人 / 跳过重复 M 人 / 跳过不符 K 人 / 失败 F 人`

注册 `btnBatchCollectNew.addEventListener('click', batchCollectNewFromList)`。

`loadJobs()` 调用时同时填充 `batchNewJobSelect`（复用现有逻辑，加一行 option append）。

### 5.3 content.js

#### 新增消息处理

```js
batchCollectNew: (msg) => batchCollectNew(
  msg.limit, msg.criteria, msg.serverUrl, msg.authToken || ''
),
```

#### 新增 `extractSchoolTier()` 工具函数

调用时机：候选人已被点击、右侧面板已完成切换之后。从当前右侧面板 DOM 提取学校层次，两步：

**Step 1**：查右侧面板中的 `.tag-item` 类型标签（Boss 在某些视图显示 985/211 tier tag）：
```js
// 匹配 /^985$|^211$|^双一流$|^\d+院校$/ 的 tag 文本
// 返回第一个命中的 tier 字符串，如 "985"
```

**Step 2**：若 Step 1 无结果，读右侧面板（`.base-info-single-detial` 区域及其他可见文本）
全文，在 `SCHOOL_985` / `SCHOOL_211` / `SCHOOL_FIRST_CLASS` 集合中做 `includes` 查找。

> **DOM 验证**：实现时须在真实 Boss 聊天页面验证右侧面板学校信息所在选择器（当前
> `extractDetail()` 仅提取学历等级，学校名可能在其他元素）。若两步均无结果，
> 返回 `'unknown'`（`matchesCriteria` 对 unknown 保守放行）。

> **实现注意**：聊天页面 `.base-info-single-detial` 的具体子节点结构需在实现时
> 对实际 Boss 页面 DOM 做一次验证。若 Step1/Step2 均未提取到学校，且 criteria
> 要求学校过滤，则保守地**放行**（不因无法确认而错误跳过），并在日志中标注
> `school_unknown`。

#### 新增三个学校集合常量

```js
const SCHOOL_985 = new Set([/* 39 所 */]);
const SCHOOL_211 = new Set([/* 116 所，含 985 */]);
const SCHOOL_FIRST_CLASS = new Set([/* 双一流学科高校，约 140 所 */]);
```

学校名使用官方简称（如"北京大学"、"清华大学"、"北京交通大学"），匹配时做 `includes` 而非精确等于，容忍前缀差异。

#### 新增 `matchesCriteria(detail, schoolTier, criteria)` 工具函数

```js
function matchesCriteria(detail, schoolTier, criteria) {
  if (!criteria) return true;
  // 学历检查
  const EDU_ORDER = ['大专','本科','硕士','博士'];
  if (criteria.education_min) {
    const minIdx = EDU_ORDER.indexOf(criteria.education_min);
    const detailIdx = EDU_ORDER.indexOf(detail.education);
    if (detailIdx < minIdx) return false;
  }
  // 学校检查
  if (criteria.school_tiers?.length) {
    if (schoolTier === 'unknown') return true; // 保守放行
    return criteria.school_tiers.some(tier => {
      if (tier === '985') return SCHOOL_985.has(schoolTier);
      if (tier === '211') return SCHOOL_211.has(schoolTier);
      if (tier === '双一流') return SCHOOL_FIRST_CLASS.has(schoolTier);
      return false;
    });
  }
  return true;
}
```

#### 新增 `batchCollectNew(limit, criteria, serverUrl, authToken)`

```
async function batchCollectNew(limit, criteria, serverUrl, authToken) {
  LOG.length = 0; _setRunning(true);
  const items = document.querySelectorAll('.geek-item');
  if (!items.length) return {success:false, message:'未找到候选人列表'};

  // ① 读全部 boss_ids
  const allIds = [...items].map(el => el.getAttribute('data-id')).filter(Boolean);

  // ② 批量查已在库的
  const existingSet = await checkBossIds(allIds, serverUrl, authToken);

  // ③ 过滤候选列表（跳过已在库的）
  const candidates = [...items].filter(el =>
    !existingSet.has(el.getAttribute('data-id'))
  );

  let collected=0, skippedDup=allIds.length - candidates.length,
      skippedCriteria=0, failed=0;
  let prevPdfTitle='';

  for (let i=0; i < candidates.length && collected < limit; i++) {
    const item = candidates[i];
    const listName = item.querySelector('.geek-name')?.textContent?.trim() || '';
    if (!listName) continue;
    log(`[${i+1}] ${listName}`);

    item.click();
    if (!await waitForNameBox(listName, 6000)) { failed++; continue; }
    await waitForChatUpdate(prevPdfTitle, 4000);
    await sleep(500);

    const detail = extractDetail();
    detail.boss_id = item.getAttribute('data-id') || '';
    supplementFromPushText(detail, item);
    const schoolTier = extractSchoolTier(); // 读点击后的右侧面板 DOM，非 list item

    if (!matchesCriteria(detail, schoolTier, criteria)) {
      log(`跳过 ${listName}: 不符标准 (学历=${detail.education} 学校=${schoolTier})`);
      skippedCriteria++; continue;
    }

    const pdfInfo = findPdfCard();
    const pdfTitle = pdfInfo?.card.querySelector('.message-card-top-title')?.textContent?.trim() || '';
    let ok = false;
    if (pdfInfo && pdfTitle && serverUrl) {
      // 用 batch_chat source 覆盖
      const r = await downloadPdf({...detail, source:'batch_chat'}, listName, serverUrl, authToken);
      ok = r.ok;
    }
    if (!ok) {
      const resp = await submitPageData({...detail, source:'batch_chat'}, serverUrl, authToken);
      ok = resp.ok;
    }
    if (ok) { collected++; prevPdfTitle = pdfTitle; }
    else { failed++; }
    await sleep(1000);
  }

  _setRunning(false);
  return {success:true, collected, skippedDup, skippedCriteria, failed,
          message:`采集 ${collected}/${limit} 人完成`};
}

async function checkBossIds(bossIds, serverUrl, authToken) {
  try {
    const headers = {'Content-Type':'application/json'};
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    const r = await fetch(`${serverUrl}/api/resumes/check-boss-ids`,
      {method:'POST', headers, body: JSON.stringify({boss_ids: bossIds})});
    const data = await r.json();
    return new Set(data.existing || []);
  } catch { return new Set(); }
}
```

---

## 6. 前端改动（Jobs.vue）

在岗位编辑 dialog 的现有表单末尾，加折叠面板"批量采集标准"：

```
─ 批量采集标准 ──────────────────────────────────
学校层次  ☑ 985   ☑ 211   ☐ 双一流   （全不选=不限）
最低学历  [不限 ▾]  （选项：不限/大专/本科/硕士/博士）
```

保存时将 `{school_tiers: [...checked], education_min: selected}` 写入
`form.batch_collect_criteria`，经现有 `PATCH /api/jobs/{id}` 保存。
读取时从 `job.batch_collect_criteria` 初始化表单。

---

## 7. 文件变更清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `migrations/versions/0016_job_batch_collect_criteria.py` | 新建 | Alembic migration |
| `app/modules/screening/models.py` | 修改 | 加 `batch_collect_criteria JSON` |
| `app/modules/screening/schemas.py` | 修改 | 加 `batch_collect_criteria` 字段 |
| `app/modules/resume/router.py` | 修改 | 加 `POST /check-boss-ids` 端点 |
| `edge_extension/popup.html` | 修改 | 新增批量采集区域 |
| `edge_extension/popup.js` | 修改 | 新增 `batchCollectNewFromList` + 按钮绑定 |
| `edge_extension/content.js` | 修改 | 新增 `batchCollectNew` / `checkBossIds` / `extractSchoolTier` / `matchesCriteria` / 三个学校常量集合 |
| `frontend/src/views/Jobs.vue` | 修改 | 岗位编辑表单加批量采集标准 |

---

## 8. 测试策略（TDD）

| 测试 | 类型 | 覆盖 |
|---|---|---|
| `test_job_batch_criteria_schema` | 单元 | JobCreate/Update/Response schema 含新字段 |
| `test_migration_0016` | 集成 | alembic upgrade/downgrade |
| `test_check_boss_ids_endpoint` | 集成 | 空列表 / 部分在库 / 全不在库 / 无鉴权 |
| `test_matchesCriteria` | JS 单元（手动验证） | 985 命中 / 211 命中 / 学历不足 / unknown 放行 / 无标准全通过 |
| E2E smoke | 手动 | 消息列表页 → 开始采集 → 日志显示跳过/成功 |

---

## 9. 边界情况

| 情况 | 处理 |
|---|---|
| 消息列表无候选人 | 返回 `未找到候选人列表` 错误 |
| 全部候选人已在库 | 返回 `skippedDup=N, collected=0`，日志说明 |
| 学校无法识别 | `school_unknown`，保守放行 |
| PDF 下载失败 | 退回页面数据提交 |
| `batch_collect_criteria` 为 null | 无过滤，采集所有新候选人 |
| 采集途中页面跳转 | `waitForNameBox` 超时 → 计 `failed`，继续下一个 |
| Boss 限流风控 | 此版本不做风控检测（batchCollect 中也无），由用户自行注意频率 |

---

## 10. 实现注意

- `extractSchoolTier()` 依赖实际 Boss 直聘聊天页面 DOM，实现时须对真实页面做一次 DOM 验证，确认 tag 选择器路径。
- 学校常量集合（985/211/双一流）在实现时从教育部公开名单整理，约 200-400 个字符串，直接硬编码在 content.js 顶部。
- `source: 'batch_chat'` 在后端 Resume 模型 `source` 字段枚举中若不存在需追加；若 `source` 为自由字符串则无需改。
- 不复用 `_paused`/`_stopped` 全局状态（避免与 batchCollect 状态互扰），新函数独立运行至完成或 limit 达到。
