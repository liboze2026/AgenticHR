# F6: 批量聊天候选人采集 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Extension popup 中批量从 Boss 直聘消息列表页采集新候选人，按岗位配置的学校层次/学历标准过滤，结果仅入简历库。

**Architecture:** 复用现有 `batchCollect` 点击/提取/PDF 流程，在其前加两层过滤（DB 去重 + 学校标准），后端加一个 boss_ids 查询端点，Job 模型加 `batch_collect_criteria` JSON 列，前端岗位编辑表单加对应设置项。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic（后端），Edge Extension MV3 + vanilla JS（扩展），Vue 3 + Element Plus（前端）

---

## 文件结构

| 文件 | 操作 | 说明 |
|---|---|---|
| `migrations/versions/0016_job_batch_collect_criteria.py` | 新建 | jobs 表加 `batch_collect_criteria JSON` |
| `app/modules/screening/models.py` | 修改 | Job 加列声明 |
| `app/modules/screening/schemas.py` | 修改 | 3 个 schema 加字段 |
| `app/modules/resume/router.py` | 修改 | 新增 `POST /check-boss-ids`；upload 端点加 `candidate_source` |
| `app/modules/resume/service.py` | 修改 | `create_from_pdf` 加 `source` 参数 |
| `tests/modules/screening/test_router.py` | 修改 | 加 batch_collect_criteria 相关测试 |
| `tests/modules/resume/test_router.py` | 修改/新建 | 加 check-boss-ids 测试 |
| `edge_extension/content.js` | 修改 | 加学校常量 + 4 个新函数 + 消息处理 |
| `edge_extension/popup.html` | 修改 | 新增批量采集区域 |
| `edge_extension/popup.js` | 修改 | 新增 `batchCollectNewFromList` + `loadBatchJobs` + 按钮绑定 |
| `frontend/src/views/Jobs.vue` | 修改 | 岗位编辑表单加批量采集标准 |

---

## Task 1: Alembic 迁移 0016 — jobs 表加 batch_collect_criteria 列

**Files:**
- 新建: `migrations/versions/0016_job_batch_collect_criteria.py`
- 测试: `tests/core/test_migration_0016.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/core/test_migration_0016.py`：

```python
"""Migration 0016: jobs.batch_collect_criteria column"""
import pytest
from sqlalchemy import create_engine, inspect, text
from alembic.config import Config
from alembic import command


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _seed_jobs(conn):
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS users "
        "(id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, "
        "display_name TEXT, is_active INTEGER DEFAULT 1, daily_cap INTEGER DEFAULT 1000)"
    ))
    conn.execute(text(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (1,'u','x')"
    ))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS jobs "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 0, "
        "title TEXT NOT NULL, department TEXT DEFAULT '', "
        "education_min TEXT DEFAULT '', work_years_min INTEGER DEFAULT 0, "
        "work_years_max INTEGER DEFAULT 99, salary_min REAL DEFAULT 0, "
        "salary_max REAL DEFAULT 0, required_skills TEXT DEFAULT '', "
        "soft_requirements TEXT DEFAULT '', greeting_templates TEXT DEFAULT '', "
        "is_active INTEGER DEFAULT 1, created_at DATETIME, updated_at DATETIME, "
        "jd_text TEXT DEFAULT '', competency_model JSON, "
        "competency_model_status TEXT DEFAULT 'none', "
        "scoring_weights JSON, greet_threshold INTEGER DEFAULT 60)"
    ))


def test_migration_0016_upgrade_adds_column(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test_0016.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        _seed_jobs(conn)
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "0015")
    command.upgrade(cfg, "0016")
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("jobs")]
    assert "batch_collect_criteria" in cols
    engine.dispose()


def test_migration_0016_downgrade_removes_column(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test_0016_down.db"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        _seed_jobs(conn)
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "0016")
    command.downgrade(cfg, "0015")
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("jobs")]
    assert "batch_collect_criteria" not in cols
    engine.dispose()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:/0jingtong/AgenticHR
.venv/Scripts/python -m pytest tests/core/test_migration_0016.py -v
```

期望: `FAILED` — 迁移文件不存在。

- [ ] **Step 3: 创建迁移文件**

新建 `migrations/versions/0016_job_batch_collect_criteria.py`：

```python
"""Add batch_collect_criteria to jobs

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("batch_collect_criteria", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("batch_collect_criteria")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/Scripts/python -m pytest tests/core/test_migration_0016.py -v
```

期望: `2 passed`

- [ ] **Step 5: 在开发数据库执行迁移**

```bash
.venv/Scripts/python -m alembic -c migrations/alembic.ini upgrade head
```

期望: `Running upgrade 0015 -> 0016`

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/0016_job_batch_collect_criteria.py tests/core/test_migration_0016.py
git commit -m "feat(f6-T1): migration 0016 — jobs.batch_collect_criteria"
```

---

## Task 2: Job 模型 + Schema 扩展

**Files:**
- 修改: `app/modules/screening/models.py`
- 修改: `app/modules/screening/schemas.py`
- 修改: `tests/modules/screening/test_router.py`

- [ ] **Step 1: 写失败测试**

在 `tests/modules/screening/test_router.py` 末尾追加：

```python
def test_job_batch_collect_criteria_create(client):
    resp = client.post("/api/screening/jobs", json={
        "title": "批采测试岗",
        "batch_collect_criteria": {"school_tiers": ["985", "211"], "education_min": "本科"},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["batch_collect_criteria"]["school_tiers"] == ["985", "211"]
    assert data["batch_collect_criteria"]["education_min"] == "本科"


def test_job_batch_collect_criteria_update(client):
    resp = client.post("/api/screening/jobs", json={"title": "批采更新岗"})
    job_id = resp.json()["id"]
    resp2 = client.patch(f"/api/screening/jobs/{job_id}", json={
        "batch_collect_criteria": {"school_tiers": [], "education_min": None}
    })
    assert resp2.status_code == 200
    assert resp2.json()["batch_collect_criteria"]["school_tiers"] == []


def test_job_batch_collect_criteria_null_by_default(client):
    resp = client.post("/api/screening/jobs", json={"title": "默认岗"})
    assert resp.status_code == 201
    assert resp.json()["batch_collect_criteria"] is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/modules/screening/test_router.py::test_job_batch_collect_criteria_create -v
```

期望: `FAILED` — `batch_collect_criteria` 字段未知。

- [ ] **Step 3: 修改 Job 模型**

编辑 `app/modules/screening/models.py`，在 `greet_threshold` 行后追加：

```python
    batch_collect_criteria = Column(JSON, nullable=True)
```

- [ ] **Step 4: 修改 3 个 Schema**

编辑 `app/modules/screening/schemas.py`：

在 `JobCreate` 类末尾（`@model_validator` 之前）追加：
```python
    batch_collect_criteria: dict | None = None
```

在 `JobUpdate` 类末尾（`@model_validator` 之前）追加：
```python
    batch_collect_criteria: dict | None = None
```

在 `JobResponse` 类中（`scoring_weights` 行后）追加：
```python
    batch_collect_criteria: dict | None = None
```

- [ ] **Step 5: 运行全部 3 个测试**

```bash
.venv/Scripts/python -m pytest tests/modules/screening/test_router.py::test_job_batch_collect_criteria_create tests/modules/screening/test_router.py::test_job_batch_collect_criteria_update tests/modules/screening/test_router.py::test_job_batch_collect_criteria_null_by_default -v
```

期望: `3 passed`

- [ ] **Step 6: 零回归检查**

```bash
.venv/Scripts/python -m pytest tests/modules/screening/ --tb=short -q
```

期望: 所有原有测试仍通过。

- [ ] **Step 7: Commit**

```bash
git add app/modules/screening/models.py app/modules/screening/schemas.py tests/modules/screening/test_router.py
git commit -m "feat(f6-T2): Job.batch_collect_criteria column + schema"
```

---

## Task 3: 后端新端点 check-boss-ids + upload source 支持

**Files:**
- 修改: `app/modules/resume/router.py`
- 修改: `app/modules/resume/service.py`
- 新建/修改: `tests/modules/resume/test_check_boss_ids.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/modules/resume/test_check_boss_ids.py`：

```python
"""POST /api/resumes/check-boss-ids 端点测试"""
import pytest


def test_check_boss_ids_empty_list(client):
    resp = client.post("/api/resumes/check-boss-ids", json={"boss_ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"existing": []}


def test_check_boss_ids_none_in_library(client):
    resp = client.post("/api/resumes/check-boss-ids", json={"boss_ids": ["boss_xxx", "boss_yyy"]})
    assert resp.status_code == 200
    assert resp.json()["existing"] == []


def test_check_boss_ids_some_in_library(client):
    # 先插入两条简历
    client.post("/api/resumes/", json={
        "name": "张三", "boss_id": "boss_aaa", "source": "boss_zhipin"
    })
    client.post("/api/resumes/", json={
        "name": "李四", "boss_id": "boss_bbb", "source": "boss_zhipin"
    })
    resp = client.post("/api/resumes/check-boss-ids", json={
        "boss_ids": ["boss_aaa", "boss_bbb", "boss_ccc"]
    })
    assert resp.status_code == 200
    existing = set(resp.json()["existing"])
    assert existing == {"boss_aaa", "boss_bbb"}


def test_check_boss_ids_user_scoped(client, client2):
    """user2 的简历不应出现在 user1 的结果里"""
    client2.post("/api/resumes/", json={"name": "王五", "boss_id": "boss_zzz"})
    resp = client.post("/api/resumes/check-boss-ids", json={"boss_ids": ["boss_zzz"]})
    assert resp.json()["existing"] == []


def test_upload_resume_with_batch_chat_source(client, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj\nxref\n0 2\n0000000000 65535 f\ntrailer<</Size 2>>\nstartxref\n9\n%%EOF")
    with open(pdf, "rb") as f:
        resp = client.post(
            "/api/resumes/upload",
            data={"candidate_name": "测试", "candidate_source": "batch_chat"},
            files={"file": ("test.pdf", f, "application/pdf")},
        )
    # 422 = PDF 内容太短无法解析；但 source 参数本身不报错
    assert resp.status_code in (200, 422)
```

> `client2` fixture 需在 `tests/conftest.py` 中存在（以 user_id=2 的 token 运行）。
> 若不存在，跳过 `test_check_boss_ids_user_scoped` 改为手动验收。

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/Scripts/python -m pytest tests/modules/resume/test_check_boss_ids.py -v --tb=short
```

期望: `FAILED` — 端点不存在返回 404 / 405。

- [ ] **Step 3: 在 router.py 添加 check-boss-ids 端点**

在 `app/modules/resume/router.py` 中，在现有 `list_resumes` 函数之前（约 159 行）插入：

```python
from pydantic import BaseModel as _BaseModel

class _CheckBossIdsIn(_BaseModel):
    boss_ids: list[str]

@router.post("/check-boss-ids")
def check_boss_ids(
    body: _CheckBossIdsIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if not body.boss_ids:
        return {"existing": []}
    rows = (
        db.query(Resume.boss_id)
        .filter(Resume.boss_id.in_(body.boss_ids), Resume.user_id == user_id,
                Resume.boss_id != "")
        .all()
    )
    return {"existing": [r.boss_id for r in rows]}
```

- [ ] **Step 4: 在 upload_pdf_resume 添加 candidate_source 参数**

在 `app/modules/resume/router.py` 的 `upload_pdf_resume` 函数签名中，在 `candidate_boss_id` 行后追加：

```python
    candidate_source: str = Form("boss_zhipin"),
```

将 `service.create_from_pdf(...)` 调用改为：

```python
    resume = service.create_from_pdf(
        str(file_path),
        page_info={
            "name": candidate_name,
            "phone": candidate_phone,
            "email": candidate_email,
            "education": candidate_education,
            "work_years": candidate_work_years,
            "job_intention": candidate_job,
        },
        original_filename=file.filename or "",
        user_id=user_id,
        boss_id=candidate_boss_id,
        source=candidate_source,
    )
```

- [ ] **Step 5: 在 service.py create_from_pdf 添加 source 参数**

在 `app/modules/resume/service.py` 的 `create_from_pdf` 函数签名中追加 `source: str = "boss_zhipin"`：

```python
    def create_from_pdf(self, file_path: str, page_info: dict | None = None,
                        original_filename: str = "", user_id: int = 0,
                        boss_id: str = "", source: str = "boss_zhipin") -> Resume | None:
```

找到函数内部硬编码 `source="boss_zhipin"` 的地方（约第 243 行）：

```python
            source="boss_zhipin",
```

改为：

```python
            source=source,
```

同理，找到 `_update_fields` 路径中如果有 source 设置的地方也改为参数值。若 `_update_fields` 不修改 source，无需额外改动。

- [ ] **Step 6: 在 router.py 的 ResumeCreate JSON 端点也支持 source**

检查 `create_resume` 函数（约 67 行）的 `ResumeCreate` schema — 若 `ResumeCreate` 中有 `source` 字段则无需改，若无则在 `app/modules/resume/schemas.py` 的 `ResumeCreate` 中追加：

```python
source: str = "boss_zhipin"
```

> 仅当该字段不存在时才添加。检查方法：`grep -n "source" app/modules/resume/schemas.py`

- [ ] **Step 7: 运行 check-boss-ids 测试**

```bash
.venv/Scripts/python -m pytest tests/modules/resume/test_check_boss_ids.py -v --tb=short
```

期望: 至少 `test_check_boss_ids_empty_list`, `test_check_boss_ids_none_in_library`, `test_check_boss_ids_some_in_library` 通过。`test_check_boss_ids_user_scoped` 若无 `client2` fixture 则 skip。

- [ ] **Step 8: 零回归**

```bash
.venv/Scripts/python -m pytest tests/ --tb=short -q
```

期望: 新增测试通过，原有测试无新增失败。

- [ ] **Step 9: Commit**

```bash
git add app/modules/resume/router.py app/modules/resume/service.py tests/modules/resume/test_check_boss_ids.py
git commit -m "feat(f6-T3): POST /resumes/check-boss-ids + upload source param"
```

---

## Task 4: content.js — 学校常量 + 4 个新函数 + 消息处理

**Files:**
- 修改: `edge_extension/content.js`

> 此 Task 无 pytest 测试，改动后需手动在 Boss 直聘消息列表页加载插件验证。

- [ ] **Step 1: 在 content.js 顶部添加学校常量集合**

在文件顶部（第 1 行或 `'use strict';` 之后）插入：

```js
// ────────────────────────────────────────────────
// 学校层次常量（教育部名单，含官方简称）
// ────────────────────────────────────────────────
const SCHOOL_985 = new Set([
  '北京大学','清华大学','中国人民大学','北京航空航天大学','北京理工大学',
  '中国农业大学','北京师范大学','中央民族大学','南开大学','天津大学',
  '大连理工大学','吉林大学','哈尔滨工业大学','复旦大学','同济大学',
  '上海交通大学','华东师范大学','南京大学','东南大学','浙江大学',
  '中国科学技术大学','厦门大学','山东大学','中国海洋大学','武汉大学',
  '华中科技大学','中南大学','中山大学','华南理工大学','四川大学',
  '重庆大学','电子科技大学','西安交通大学','西北工业大学','兰州大学',
  '国防科技大学','中国科学院大学','东北大学','湖南大学',
]);

// 211 包含 985
const SCHOOL_211 = new Set([
  ...SCHOOL_985,
  '北京交通大学','北京工业大学','北京科技大学','北京化工大学',
  '北京邮电大学','北京林业大学','北京中医药大学','中央音乐学院',
  '对外经济贸易大学','中国政法大学','华北电力大学','中国矿业大学',
  '河海大学','江南大学','南京农业大学','中国药科大学','南京航空航天大学',
  '南京理工大学','苏州大学','东北财经大学','大连海事大学','延边大学',
  '东北林业大学','东北农业大学','华东理工大学','东华大学','上海大学',
  '上海外国语大学','上海财经大学','合肥工业大学','中国地质大学',
  '武汉理工大学','华中农业大学','华中师范大学','中南财经政法大学',
  '湖南师范大学','暨南大学','华南师范大学','广西大学','海南大学',
  '西南大学','西南交通大学','西南财经大学','四川农业大学','贵州大学',
  '云南大学','西藏大学','西北农林科技大学','陕西师范大学','长安大学',
  '新疆大学','石河子大学','宁夏大学','青海大学','内蒙古大学',
  '太原理工大学','河北工业大学','燕山大学','山西大学',
  '郑州大学','安徽大学','南昌大学','福州大学',
]);

// 双一流学科高校（部分非211）
const SCHOOL_FIRST_CLASS = new Set([
  ...SCHOOL_211,
  '北京协和医学院','外交学院','中央财经大学','北京外国语大学',
  '华南农业大学','广州医科大学','南方科技大学','上海科技大学',
  '深圳大学','西湖大学',
]);
```

> 以上列表为示例，实现时可按实际教育部公告补全至完整 211/双一流名单。

- [ ] **Step 2: 添加 `extractSchoolTier()` 函数**

在 `supplementFromPushText` 函数之后插入：

```js
function extractSchoolTier() {
  // Step 1: 查右侧面板的 tier tag（.tag-item 文本匹配 985/211/双一流）
  const TIER_RE = /^985$|^211$|^双一流$|^\d+院校$/;
  const panel = document.querySelector('.geek-detail') || document.querySelector('.geek-sidebar') || document.body;
  const tagEls = panel.querySelectorAll('.tag-item, .tag, .edu-tag');
  for (const el of tagEls) {
    const txt = el.textContent.trim();
    if (TIER_RE.test(txt)) {
      if (/985/.test(txt)) return '985';
      if (/211/.test(txt)) return '211';
      if (/双一流/.test(txt)) return '双一流';
    }
  }
  // Step 2: 全文搜索学校名（.base-info-single-detial 及聊天区域）
  const panelText = (
    document.querySelector('.base-info-single-detial')?.textContent || ''
  ) + ' ' + (document.querySelector('.geek-header')?.textContent || '');
  for (const school of SCHOOL_985) {
    if (panelText.includes(school)) return '985';
  }
  for (const school of SCHOOL_211) {
    if (panelText.includes(school)) return '211';
  }
  for (const school of SCHOOL_FIRST_CLASS) {
    if (panelText.includes(school)) return '双一流';
  }
  return 'unknown';
}
```

- [ ] **Step 3: 添加 `matchesCriteria(detail, schoolTier, criteria)` 函数**

在 `extractSchoolTier` 之后插入：

```js
function matchesCriteria(detail, schoolTier, criteria) {
  if (!criteria) return true;
  const EDU_ORDER = ['大专', '本科', '硕士', '博士'];
  if (criteria.education_min) {
    const minIdx = EDU_ORDER.indexOf(criteria.education_min);
    const detailIdx = EDU_ORDER.indexOf(detail.education);
    if (minIdx >= 0 && detailIdx >= 0 && detailIdx < minIdx) return false;
  }
  if (criteria.school_tiers && criteria.school_tiers.length > 0) {
    if (schoolTier === 'unknown') return true; // 保守放行
    const match = criteria.school_tiers.some(tier => {
      if (tier === '985') return SCHOOL_985.has(schoolTier) || schoolTier === '985';
      if (tier === '211') return SCHOOL_211.has(schoolTier) || schoolTier === '211';
      if (tier === '双一流') return SCHOOL_FIRST_CLASS.has(schoolTier) || schoolTier === '双一流';
      return false;
    });
    if (!match) return false;
  }
  return true;
}
```

- [ ] **Step 4: 添加 `checkBossIds(bossIds, serverUrl, authToken)` 函数**

在 `matchesCriteria` 之后插入：

```js
async function checkBossIds(bossIds, serverUrl, authToken) {
  if (!bossIds.length || !serverUrl) return new Set();
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    const r = await fetch(`${serverUrl}/api/resumes/check-boss-ids`, {
      method: 'POST', headers,
      body: JSON.stringify({ boss_ids: bossIds }),
    });
    if (!r.ok) return new Set();
    const data = await r.json();
    return new Set(data.existing || []);
  } catch { return new Set(); }
}
```

- [ ] **Step 5: 修改 `submitPageData` 接受可选 source 参数**

找到现有 `submitPageData(d, url, authToken = '')` 函数，改为：

```js
async function submitPageData(d, url, authToken = '', source = 'boss_zhipin') {
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  return fetch(`${url}/api/resumes/`, { method: 'POST', headers,
    body: JSON.stringify({ name: d.name, phone: d.phone||'', email: d.email||'', education: d.education||'',
      work_years: d.work_years||0, job_intention: d.job_intention||'', skills: '', work_experience: d.work_experience||'',
      source: source, raw_text: d.raw_text||'', boss_id: d.boss_id||'' }) });
}
```

- [ ] **Step 6: 添加 `batchCollectNew(limit, criteria, serverUrl, authToken)` 函数**

在 `batchCollect` 函数之后（约 165 行之后）插入完整函数：

```js
async function batchCollectNew(limit, criteria, serverUrl, authToken = '') {
  LOG.length = 0; _setRunning(true);
  const items = document.querySelectorAll('.geek-item');
  if (!items.length) { _setRunning(false); return { success: false, message: '未找到候选人列表' }; }

  log(`消息列表共 ${items.length} 人，目标采集 ${limit} 人`);

  // ① 读全部 boss_ids
  const allIds = [...items].map(el => el.getAttribute('data-id')).filter(Boolean);

  // ② 批量查已在库的
  const existingSet = await checkBossIds(allIds, serverUrl, authToken);
  log(`已在库: ${existingSet.size} 人，将跳过`);

  // ③ 过滤已在库的
  const candidates = [...items].filter(el => !existingSet.has(el.getAttribute('data-id')));
  const skippedDup = allIds.length - candidates.length;

  let collected = 0, skippedCriteria = 0, failed = 0;
  let prevPdfTitle = '';

  for (let i = 0; i < candidates.length && collected < limit; i++) {
    const item = candidates[i];
    const listName = item.querySelector('.geek-name')?.textContent?.trim() || '';
    if (!listName) continue;
    log(`\n── [${i+1}/${candidates.length}] ${listName} ──`);

    item.click();
    if (!await waitForNameBox(listName, 6000)) {
      log('面板未切换，跳过'); failed++; continue;
    }
    await waitForChatUpdate(prevPdfTitle, 4000);
    await sleep(500);

    const detail = extractDetail();
    detail.boss_id = item.getAttribute('data-id') || '';
    supplementFromPushText(detail, item);
    const schoolTier = extractSchoolTier();

    log(`学历=${detail.education} 学校层次=${schoolTier}`);

    if (!matchesCriteria(detail, schoolTier, criteria)) {
      log(`跳过: 不符标准`); skippedCriteria++; continue;
    }

    const pdfInfo = findPdfCard();
    const pdfTitle = pdfInfo?.card.querySelector('.message-card-top-title')?.textContent?.trim() || '';
    let ok = false;

    if (pdfInfo && pdfTitle && serverUrl) {
      // downloadPdf 内部调用 /api/resumes/upload，加 source 参数
      const r = await downloadPdfWithSource(detail, listName, serverUrl, authToken, 'batch_chat');
      ok = r.ok;
      if (ok) prevPdfTitle = pdfTitle;
    }
    if (!ok) {
      const resp = await submitPageData(detail, serverUrl, authToken, 'batch_chat');
      ok = resp.ok;
    }
    if (ok) { collected++; log(`采集成功 (${collected}/${limit})`); }
    else { failed++; log('采集失败'); }
    await sleep(1000);
  }

  _setRunning(false);
  return {
    success: true, collected, skippedDup, skippedCriteria, failed,
    message: `采集 ${collected}/${limit} 人完成`,
  };
}
```

- [ ] **Step 7: 添加 `downloadPdfWithSource` 包装函数**

`downloadPdf` 内部 FormData 不传 source。新增一个薄包装，在上传前追加 source 字段。在 `downloadPdf` 函数定义之后插入：

```js
async function downloadPdfWithSource(candidateInfo, expectedName, serverUrl, authToken, source) {
  // 复用 downloadPdf 的所有逻辑，但在 upload 前追加 candidate_source
  // 由于 downloadPdf 内部直接构建 FormData 并 fetch，这里做一个轻量封装：
  // 先调用 downloadPdf，若其内部 upload 成功则已用默认 source；
  // 为支持自定义 source，直接在 candidateInfo 里携带 source 字段，
  // 并在 downloadPdf 中读取 candidateInfo.source（需 Step 8 修改 downloadPdf）。
  return downloadPdf({ ...candidateInfo, source }, expectedName, serverUrl, authToken);
}
```

- [ ] **Step 8: 修改 `downloadPdf` 内的 FormData 追加 candidate_source**

在 `downloadPdf` 函数内，找到 `form.append('candidate_boss_id', ...)` 那一行（约 323 行），在其后追加：

```js
    if (candidateInfo.source) form.append('candidate_source', candidateInfo.source);
```

- [ ] **Step 9: 在消息处理器中注册 batchCollectNew action**

在 `chrome.runtime.onMessage.addListener` 的 handler 对象里，找到 `batchCollect` 那行，在其后追加：

```js
    batchCollectNew: (msg) => batchCollectNew(
      msg.limit, msg.criteria, msg.serverUrl, msg.authToken || ''
    ),
```

- [ ] **Step 10: 手动验证**

在 Edge 中加载解压扩展（`edge://extensions` → 开发者模式 → 加载解压缩的扩展）。打开 Boss 直聘消息列表页，在控制台运行：

```js
// 测试 matchesCriteria（F12 控制台中）
// 先确认常量已加载
console.log(SCHOOL_985.has('清华大学')); // true
console.log(matchesCriteria({education:'本科'}, '985', {school_tiers:['985'], education_min:'本科'})); // true
console.log(matchesCriteria({education:'大专'}, '985', {school_tiers:['985'], education_min:'本科'})); // false
console.log(matchesCriteria({education:'本科'}, 'unknown', {school_tiers:['985']})); // true (保守放行)
```

- [ ] **Step 11: Commit**

```bash
git add edge_extension/content.js
git commit -m "feat(f6-T4): content.js school constants + extractSchoolTier + matchesCriteria + batchCollectNew"
```

---

## Task 5: popup.html + popup.js 新按钮

**Files:**
- 修改: `edge_extension/popup.html`
- 修改: `edge_extension/popup.js`

- [ ] **Step 1: 在 popup.html 的消息列表卡片内追加批量采集新候选人区域**

找到 `id="cardList"` 的 div（消息列表批量操作卡片），在 `<div class="card-hint">` 之前插入：

```html
      <div style="margin-top:8px;border-top:1px solid #eee;padding-top:8px;">
        <div style="font-size:11px;color:#666;margin-bottom:4px;">批量采集新候选人（按标准筛选）</div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <select id="batchNewJobSelect" style="flex:1;min-width:100px;font-size:12px;padding:2px 4px;"></select>
          <input id="batchNewLimit" type="number" min="1" max="50" value="10"
            style="width:52px;font-size:12px;padding:2px 4px;border:1px solid #ddd;border-radius:3px;" title="采集数量上限">
          <button class="btn btn-primary" id="btnBatchCollectNew"
            style="font-size:12px;padding:4px 10px;">开始采集</button>
        </div>
      </div>
```

- [ ] **Step 2: 在 popup.js 顶部声明新 DOM 元素引用**

找到 `const btnBatchCollect = ...` 那行，在其后添加：

```js
const btnBatchCollectNew = document.getElementById('btnBatchCollectNew');
const batchNewJobSelect = document.getElementById('batchNewJobSelect');
const batchNewLimit = document.getElementById('batchNewLimit');
```

- [ ] **Step 3: 在 popup.js 中添加 `loadBatchJobs()` 函数**

在现有 `loadJobs()` 函数之后插入（注意：这个函数不过滤 competency_model_status，显示所有活跃岗位）：

```js
async function loadBatchJobs() {
  const url = getServerUrl();
  const token = getAuthToken();
  if (!token || !batchNewJobSelect) return;
  try {
    const r = await fetch(`${url}/api/screening/jobs?active_only=true`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return;
    const data = await r.json();
    batchNewJobSelect.innerHTML = '<option value="">-- 选择岗位 --</option>';
    const jobs = Array.isArray(data) ? data : (data.items || []);
    jobs.forEach(j => {
      const opt = document.createElement('option');
      opt.value = j.id;
      opt.dataset.criteria = JSON.stringify(j.batch_collect_criteria || null);
      opt.textContent = j.title || `岗位${j.id}`;
      batchNewJobSelect.appendChild(opt);
    });
  } catch (e) {
    console.error('loadBatchJobs fail', e);
  }
}
```

- [ ] **Step 4: 在 popup.js 现有 `loadJobs` 调用处同时调用 `loadBatchJobs`**

找到所有 `await loadJobs()` 调用（约 84 行和 176 行），在其后各加一行：

```js
    await loadBatchJobs();
```

- [ ] **Step 5: 添加 `batchCollectNewFromList()` 函数**

在 `batchCollectFromList` 函数之后插入：

```js
async function batchCollectNewFromList() {
  const url = saveServerUrl();
  const token = getAuthToken();
  if (!token) { showResult('请先登录', 'error'); return; }

  const jobId = parseInt(batchNewJobSelect?.value, 10);
  if (!jobId) { showResult('请选择岗位', 'error'); return; }

  const limit = parseInt(batchNewLimit?.value, 10) || 10;
  if (limit < 1 || limit > 50) { showResult('采集数量须为 1-50', 'error'); return; }

  // 读 criteria from selected option dataset
  let criteria = null;
  const selOpt = batchNewJobSelect?.selectedOptions?.[0];
  try { criteria = JSON.parse(selOpt?.dataset?.criteria || 'null'); } catch { criteria = null; }

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.includes('zhipin.com')) {
      showResult('请在Boss直聘页面使用此功能', 'error'); return;
    }
    let pingResp;
    try { pingResp = await chrome.tabs.sendMessage(tab.id, { action: 'ping' }); } catch {
      showResult('请先刷新Boss直聘页面', 'error'); return;
    }
    if (!pingResp?.onMessagePage) {
      showResult('请先打开Boss直聘「消息」页面', 'error'); return;
    }
  } catch { showResult('请先刷新Boss直聘页面', 'error'); return; }

  showResult(`开始批量采集，目标 ${limit} 人，标准: ${JSON.stringify(criteria) || '无限制'}\n请勿操作Boss直聘页面！`, '');
  setButtonsDisabled(true);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const response = await chrome.tabs.sendMessage(tab.id, {
      action: 'batchCollectNew', limit, criteria, serverUrl: url, authToken: token,
    });
    if (!response?.success) {
      showResult(`采集失败: ${response?.message || '无响应，请刷新页面重试'}`, 'error');
      setButtonsDisabled(false); return;
    }
    const { collected, skippedDup, skippedCriteria, failed } = response;
    showResult(
      `✅ 采集完成\n成功入库: ${collected} 人\n跳过(已在库): ${skippedDup} 人\n跳过(不符标准): ${skippedCriteria} 人\n失败: ${failed} 人`,
      collected > 0 ? 'success' : ''
    );
  } catch (e) {
    showResult(`异常: ${e.message}`, 'error');
  } finally {
    setButtonsDisabled(false);
  }
}
```

- [ ] **Step 6: 注册按钮事件**

在 `btnBatchCollect.addEventListener(...)` 之后追加：

```js
if (btnBatchCollectNew) btnBatchCollectNew.addEventListener('click', batchCollectNewFromList);
```

- [ ] **Step 7: 在 `setButtonsDisabled` 中包含新按钮**

找到 `setButtonsDisabled(disabled)` 函数，在其中加入：

```js
  if (btnBatchCollectNew) btnBatchCollectNew.disabled = disabled;
```

- [ ] **Step 8: 手动验证 popup**

1. 重新加载扩展
2. 打开 Boss 直聘消息列表页
3. 打开 popup — 确认"批量采集新候选人"区域可见，岗位下拉有内容
4. 选岗位 + 设置数量 + 点"开始采集" — 确认日志显示进度

- [ ] **Step 9: Commit**

```bash
git add edge_extension/popup.html edge_extension/popup.js
git commit -m "feat(f6-T5): popup batch collect new candidates button + wiring"
```

---

## Task 6: Jobs.vue — 批量采集标准表单

**Files:**
- 修改: `frontend/src/views/Jobs.vue`

- [ ] **Step 1: 在 `defaultForm` 中追加 `batch_collect_criteria` 初始值**

找到 `const defaultForm = { title: '', department: '', ... }` 那行（约 325 行），在对象末尾追加：

```js
const defaultForm = { title: '', department: '', education_min: '', work_years_min: 0, work_years_max: 99, salary_min: 0, salary_max: 0, required_skills: '', soft_requirements: '', greeting_templates: '', jd_text: '',
  batch_collect_criteria: null
}
```

- [ ] **Step 2: 在 parseJd 返回后的 jobForm 赋值中加 batch_collect_criteria**

找到 `parseJd()` 函数内 `jobForm.value = { title: result.title || '', ... }` 那段赋值，在末尾追加：

```js
      batch_collect_criteria: { school_tiers: [], education_min: null },
```

- [ ] **Step 3: 在岗位编辑表单末尾加批量采集标准 el-form-item**

找到 `<el-form :model="jobForm" label-width="100px">` 内最后一个 `</el-form-item>` 之后，在 `</el-form>` 之前插入：

```html
              <el-form-item label="批量采集标准">
                <div style="display:flex;flex-direction:column;gap:8px;">
                  <div>
                    <span style="font-size:12px;color:#666;margin-right:8px;">学校层次：</span>
                    <el-checkbox
                      v-model="batchSchool985"
                      @change="syncBatchCriteria"
                    >985</el-checkbox>
                    <el-checkbox
                      v-model="batchSchool211"
                      @change="syncBatchCriteria"
                      style="margin-left:8px;"
                    >211</el-checkbox>
                    <el-checkbox
                      v-model="batchSchoolFirst"
                      @change="syncBatchCriteria"
                      style="margin-left:8px;"
                    >双一流</el-checkbox>
                    <span style="font-size:11px;color:#999;margin-left:8px;">（全不选=不限学校）</span>
                  </div>
                  <div>
                    <span style="font-size:12px;color:#666;margin-right:8px;">最低学历：</span>
                    <el-select
                      v-model="batchEduMin"
                      @change="syncBatchCriteria"
                      style="width:120px;"
                    >
                      <el-option label="不限" :value="null" />
                      <el-option label="大专" value="大专" />
                      <el-option label="本科" value="本科" />
                      <el-option label="硕士" value="硕士" />
                      <el-option label="博士" value="博士" />
                    </el-select>
                  </div>
                </div>
              </el-form-item>
```

- [ ] **Step 4: 在 `<script setup>` 中添加 checkbox 状态变量和同步函数**

找到 `const jobForm = ref(...)` 之后，插入：

```js
const batchSchool985 = ref(false)
const batchSchool211 = ref(false)
const batchSchoolFirst = ref(false)
const batchEduMin = ref(null)

function syncBatchCriteria() {
  const tiers = []
  if (batchSchool985.value) tiers.push('985')
  if (batchSchool211.value) tiers.push('211')
  if (batchSchoolFirst.value) tiers.push('双一流')
  // 全空时写 null（不限制），避免后端存空 dict
  if (tiers.length === 0 && !batchEduMin.value) {
    jobForm.value.batch_collect_criteria = null
  } else {
    jobForm.value.batch_collect_criteria = {
      school_tiers: tiers,
      education_min: batchEduMin.value || null,
    }
  }
}

function loadBatchCriteriaFromForm() {
  const c = jobForm.value.batch_collect_criteria
  if (!c) { batchSchool985.value = false; batchSchool211.value = false; batchSchoolFirst.value = false; batchEduMin.value = null; return; }
  batchSchool985.value = (c.school_tiers || []).includes('985')
  batchSchool211.value = (c.school_tiers || []).includes('211')
  batchSchoolFirst.value = (c.school_tiers || []).includes('双一流')
  batchEduMin.value = c.education_min || null
}
```

- [ ] **Step 5: 在 `openNewJob()` 和 `editJob()` 中调用 `loadBatchCriteriaFromForm()`**

在 `openNewJob()` 函数末尾（`showCreateDialog.value = true` 之前）追加：

```js
  loadBatchCriteriaFromForm()
```

在 `editJob()` 函数末尾（`showCreateDialog.value = true` 之前）追加：

```js
  loadBatchCriteriaFromForm()
```

- [ ] **Step 6: 构建前端确认无 TS 错误**

```bash
cd D:/0jingtong/AgenticHR/frontend
pnpm build 2>&1 | tail -10
```

期望: `✓ built in` 无报错。

- [ ] **Step 7: 手动验证**

1. 启动后端：`cd D:/0jingtong/AgenticHR && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000`
2. 启动前端：`cd frontend && pnpm dev`
3. 浏览器打开前端 → 岗位管理 → 编辑一个岗位
4. 确认表单底部出现"批量采集标准"区域
5. 勾选 985 + 211，最低学历选"本科"，保存
6. 重新编辑该岗位，确认设置已保留

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/Jobs.vue
git commit -m "feat(f6-T6): Jobs.vue batch_collect_criteria form fields"
```

---

## Task 7: 全量回归 + 推送

- [ ] **Step 1: 全量 pytest**

```bash
cd D:/0jingtong/AgenticHR
.venv/Scripts/python -m pytest tests/ --tb=short -q
```

期望：新增测试通过，原有测试无新增失败（允许原有 37 个 pre-existing failures 保持不变）。

- [ ] **Step 2: 前端构建**

```bash
cd frontend && pnpm build 2>&1 | tail -5
```

期望：`✓ built`

- [ ] **Step 3: 推送**

```bash
cd D:/0jingtong/AgenticHR
git push origin main
```

---

## 注意事项（给实现者）

1. **DOM 验证**：`extractSchoolTier()` 的 Step 2 扫描 `.base-info-single-detial` 和 `.geek-header`。在真实 Boss 页面开 F12 确认学校名在哪个节点，必要时加更多选择器。若不确定，Step 1（tag 匹配）已覆盖大多数情况。

2. **`client2` fixture**：`test_check_boss_ids_user_scoped` 需要以 user_id=2 运行的 TestClient。检查 `tests/conftest.py` 是否已有此 fixture；若无，可直接 `pytest.skip` 该测试。

3. **`downloadPdfWithSource`**：本计划通过在 `candidateInfo` 里传 `source` 字段、并在 `downloadPdf` 内读取 `candidateInfo.source` 追加到 FormData 的方式实现。确保 `downloadPdf` 的 `candidateInfo.source` 读取逻辑在所有现有调用路径中不破坏默认行为（默认 `boss_zhipin`）。

4. **`submitPageData` boss_id**：原函数没有传 `boss_id`，Task 4 Step 5 已在 JSON body 中加入 `boss_id: d.boss_id||''`。确认后端 `ResumeCreate` schema 有 `boss_id` 字段（已有 `boss_id = Column(String(100), ...)`），若 schema 缺失需同步加。

5. **学校列表完整性**：本计划的常量列表是示例缩写版，实现时建议补全至官方完整名单（教育部网站可下载），确保"中国人民大学"、"北京外国语大学"等常见学校均收录。
