# F3: Boss 推荐牛人自动打招呼 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AgenticHR 接入 Boss 直聘"推荐牛人"页（`/web/chat/recommend`）的自动打招呼链路：扩展抓 list card 字段 → 后端复用 F2 `MatchingService.score_pair` 打分 → 超岗位阈值即点 Boss 默认"打招呼"按钮；全程审计 + 反检测熔断 + 每 HR 每日配额。

**Architecture:**
- 混合架构（A3）：scrape 在 Edge 扩展 content.js 里（LIST-only 字段），decide 在后端新模块 `app/modules/recruit_bot/`。
- 后端 4 端点：`POST /api/recruit/evaluate_and_record`、`POST /api/recruit/record-greet`、`GET /api/recruit/daily-usage`、`PUT /api/recruit/daily-cap`。
- DB 改动：`users.daily_cap`、`jobs.greet_threshold`、`resumes.{boss_id, greet_status, greeted_at}` + `UNIQUE(user_id, boss_id)`。Alembic 迁移 `0010`。
- 前端：popup 加新 section（岗位下拉 + 配额 + 开始按钮），content.js 加 `autoGreetRecommend()` 主循环 + `simulateHumanClick` + `detectRiskControl`。
- 反检测硬约束：随机 2-5s 间隔、每 10 个长停 3-6s、事件序列（mouseover→mousedown→mouseup→click）、风控 DOM/文案扫描 halt、熔断。

**Tech Stack:** Python 3.11 · FastAPI · SQLAlchemy · Alembic 1.14 · Pydantic v2 · pytest · Vue（popup 无需，纯 HTML+JS）· Chrome Manifest V3。

**Design Reference:** [2026-04-21-f3-boss-recommend-auto-greet-design.md](../specs/2026-04-21-f3-boss-recommend-auto-greet-design.md)

---

## 前置约束

- **TDD 强制**：每任务先写失败测试，再实现。不可跳。
- **`core/` 不改**：本计划无 `core/*` 改动。如遇需改 `core/*` 的场景，**停下来问用户**。
- **基线维持**：F2 合并后基线 `pytest tests/ -q --ignore=tests/e2e` = 373 passed / 7 failed（7 = M2 scheduling pydantic 预存）。F3 预期新增 ~21 测试，合并前应 ~394 passed / 7 failed。
- **提交频度**：每个 Step 5 commit（跨 Task 不合并 commit）。
- **中文 docstring**：沿用现代码风格。
- **反检测约束**：spec §7 全链路，任何 scrape/click 路径违反（如直接 `.click()` 不走事件序列）= plan 偏差，停下来问。
- **禁主账号**：spec §7.5 — 测试和演示都用 HR 小号。

---

## 文件结构规划

### 新建

```
app/modules/recruit_bot/
├── __init__.py
├── models.py            # 无新 ORM（复用 Resume/Job/User）
├── schemas.py           # ScrapedCandidate, RecruitDecision, UsageInfo, ...
├── service.py           # RecruitBotService (upsert/evaluate/record_greet/usage)
└── router.py            # 4 个端点

migrations/versions/0010_f3_recruit_bot_fields.py

tests/modules/recruit_bot/
├── __init__.py
├── test_schemas.py                 # Pydantic 校验
├── test_upsert_resume.py           # upsert_resume_by_boss_id
├── test_evaluate_and_record.py     # 核心决策
├── test_record_greet.py            # record_greet_sent 幂等
├── test_daily_usage.py             # get_daily_usage per-user
├── test_router_evaluate.py         # POST /evaluate_and_record
├── test_router_record_greet.py     # POST /record-greet
├── test_router_daily_usage.py      # GET+PUT /daily-*
└── test_integration.py             # 端到端 5 测试
```

### 修改

```
app/modules/auth/models.py            # User + daily_cap 字段
app/modules/screening/models.py       # Job + greet_threshold 字段
app/modules/resume/models.py          # Resume + boss_id/greet_status/greeted_at 字段
app/main.py                           # include_router("/api/recruit")
app/config.py                         # F3_DEFAULT_GREET_THRESHOLD / F3_DEFAULT_DAILY_CAP / F3_AI_PARSE_ENABLED
edge_extension/popup.html             # F3 section (岗位下拉 + 配额 + 按钮)
edge_extension/popup.js               # loadJobs/loadDailyUsage/startAutoRecruit/editCap
edge_extension/content.js             # autoGreetRecommend + scrapeRecommendCard + simulateHumanClick + detectRiskControl
CHANGELOG.md                          # F3 入项
```

---

## 任务依赖图

```
T0 (迁移 + models + schemas)
 ├─ T2 (service.upsert_resume_by_boss_id)
 │   └─ T3 (service.evaluate_and_record)
 │       └─ T4 (service.record_greet_sent + get_daily_usage)
 │           └─ T5 (router 4 端点)
 │               └─ T9 (集成测试)
 │                   └─ T10 (手工 E2E + CHANGELOG + 合并)
 └─ T1 (content.js DOM selectors 常量文件)
     └─ T6 (content.js scrape + 反检测工具)
         └─ T7 (content.js autoGreetRecommend 主循环)
             └─ T8 (popup F3 section)
                 └─ T9
```

T1/T2-T5 可并行。T6 依赖 T1，T7 依赖 T6，T8 依赖 T7。T9 集成依赖 T5+T8。

---

## Task 0: Alembic 迁移 + models 字段 + schemas

**Files:**
- Create: `migrations/versions/0010_f3_recruit_bot_fields.py`
- Create: `app/modules/recruit_bot/__init__.py`
- Create: `app/modules/recruit_bot/schemas.py`
- Modify: `app/modules/auth/models.py`
- Modify: `app/modules/screening/models.py`
- Modify: `app/modules/resume/models.py`
- Modify: `app/config.py`
- Create: `tests/modules/recruit_bot/__init__.py`
- Create: `tests/modules/recruit_bot/test_schemas.py`

- [ ] **Step 1: 写 schema 测试（失败）**

创建 `tests/modules/recruit_bot/__init__.py`（空文件）。

创建 `tests/modules/recruit_bot/test_schemas.py`：

```python
"""recruit_bot Pydantic schemas 校验."""
import pytest
from pydantic import ValidationError


def test_scraped_candidate_minimal():
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(name="张三", boss_id="abc123")
    assert c.name == "张三"
    assert c.boss_id == "abc123"
    assert c.age is None
    assert c.skill_tags == []


def test_scraped_candidate_requires_boss_id():
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    with pytest.raises(ValidationError):
        ScrapedCandidate(name="张三", boss_id="")


def test_scraped_candidate_full():
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(
        name="李四", boss_id="xyz",
        age=28, education="硕士", grad_year=2027, work_years=3,
        school="清华", major="CS", intended_job="后端工程师",
        skill_tags=["Python", "Redis"],
        school_tier_tags=["985院校"],
        ranking_tags=["专业前10%"],
        expected_salary="30-40K", active_status="刚刚活跃",
        recommendation_reason="来自相似职位Python",
        latest_work_brief="2022.01 - 2024.12 字节 · 后端",
        raw_text="...", boss_current_job_title="全栈工程师",
    )
    assert c.work_years == 3
    assert "Python" in c.skill_tags


def test_recruit_decision_literal():
    from app.modules.recruit_bot.schemas import RecruitDecision
    d = RecruitDecision(decision="should_greet", resume_id=1, score=75, threshold=60)
    assert d.decision == "should_greet"


def test_recruit_decision_invalid():
    from app.modules.recruit_bot.schemas import RecruitDecision
    with pytest.raises(ValidationError):
        RecruitDecision(decision="invalid_state")


def test_usage_info_shape():
    from app.modules.recruit_bot.schemas import UsageInfo
    u = UsageInfo(used=10, cap=1000, remaining=990)
    assert u.remaining == 990


def test_greet_record_request():
    from app.modules.recruit_bot.schemas import GreetRecordRequest
    r = GreetRecordRequest(resume_id=1, success=True)
    assert r.error_msg == ""
    r2 = GreetRecordRequest(resume_id=2, success=False, error_msg="button_not_found")
    assert r2.error_msg == "button_not_found"
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
cd D:/libz/AgenticHR && python -m pytest tests/modules/recruit_bot/test_schemas.py -v
```

预期：`ModuleNotFoundError: No module named 'app.modules.recruit_bot'`。

- [ ] **Step 3: 写 schemas.py**

创建 `app/modules/recruit_bot/__init__.py`（空）。

创建 `app/modules/recruit_bot/schemas.py`：

```python
"""F3 recruit_bot 请求 / 响应 Pydantic schemas."""
from typing import Literal
from pydantic import BaseModel, Field


class ScrapedCandidate(BaseModel):
    """Edge 扩展从 Boss 推荐列表 list card 抠出的字段.

    LIST-only 策略：spec §5.2. 不开 modal，字段全部来自 list 卡片可见区.
    """
    name: str = Field(..., min_length=1, max_length=100)
    boss_id: str = Field(..., min_length=1, max_length=100)
    age: int | None = None
    education: str = ""
    grad_year: int | None = None
    work_years: int = 0
    school: str = ""
    major: str = ""
    intended_job: str = ""
    skill_tags: list[str] = Field(default_factory=list)
    school_tier_tags: list[str] = Field(default_factory=list)
    ranking_tags: list[str] = Field(default_factory=list)
    expected_salary: str = ""
    active_status: str = ""
    recommendation_reason: str = ""
    latest_work_brief: str = ""
    raw_text: str = ""
    boss_current_job_title: str = ""


class RecruitEvaluateRequest(BaseModel):
    job_id: int
    candidate: ScrapedCandidate


class RecruitDecision(BaseModel):
    """后端对单候选人的决策."""
    decision: Literal[
        "should_greet",
        "skipped_already_greeted",
        "rejected_low_score",
        "blocked_daily_cap",
        "error_no_competency",
    ]
    resume_id: int | None = None
    score: int | None = None
    threshold: int | None = None
    reason: str = ""


class GreetRecordRequest(BaseModel):
    resume_id: int
    success: bool
    error_msg: str = ""


class UsageInfo(BaseModel):
    used: int
    cap: int
    remaining: int


class DailyCapUpdateRequest(BaseModel):
    cap: int = Field(..., ge=0, le=10000)
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
python -m pytest tests/modules/recruit_bot/test_schemas.py -v
```

预期：7 passed。

- [ ] **Step 5: commit schemas**

```bash
git add app/modules/recruit_bot/__init__.py app/modules/recruit_bot/schemas.py tests/modules/recruit_bot/__init__.py tests/modules/recruit_bot/test_schemas.py
git commit -m "feat(f3-T0): recruit_bot schemas + 7 validation tests"
```

- [ ] **Step 6: User 模型加 daily_cap**

修改 `app/modules/auth/models.py` — 在 `created_at` 后加：

```python
    daily_cap = Column(Integer, default=1000, nullable=False)
```

完整文件头保持现状，class User 变成：

```python
"""用户模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    display_name = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    daily_cap = Column(Integer, default=1000, nullable=False)
```

- [ ] **Step 7: Job 模型加 greet_threshold**

修改 `app/modules/screening/models.py` — class Job 最后加：

```python
    greet_threshold = Column(Integer, default=60, nullable=False)
```

- [ ] **Step 8: Resume 模型加 boss_id / greet_status / greeted_at**

修改 `app/modules/resume/models.py` — 在 `seniority` 字段后加：

```python
    boss_id = Column(String(100), default="", nullable=False, index=True)
    greet_status = Column(String(20), default="none", nullable=False)
    greeted_at = Column(DateTime, nullable=True)
```

- [ ] **Step 9: 写 Alembic 迁移**

创建 `migrations/versions/0010_f3_recruit_bot_fields.py`：

```python
"""F3 recruit_bot fields: users.daily_cap, jobs.greet_threshold, resumes.{boss_id, greet_status, greeted_at} + UNIQUE(user_id, boss_id)

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column('daily_cap', sa.Integer(), server_default='1000', nullable=False)
        )

    with op.batch_alter_table('jobs') as batch_op:
        batch_op.add_column(
            sa.Column('greet_threshold', sa.Integer(), server_default='60', nullable=False)
        )

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.add_column(
            sa.Column('boss_id', sa.String(100), server_default='', nullable=False)
        )
        batch_op.add_column(
            sa.Column('greet_status', sa.String(20), server_default='none', nullable=False)
        )
        batch_op.add_column(
            sa.Column('greeted_at', sa.DateTime(), nullable=True)
        )
        batch_op.create_index('ix_resumes_boss_id', ['boss_id'])

    # 部分唯一索引 (SQLite 支持 WHERE 子句)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_resumes_user_boss "
        "ON resumes(user_id, boss_id) WHERE boss_id != ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_resumes_user_boss")

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.drop_index('ix_resumes_boss_id')
        batch_op.drop_column('greeted_at')
        batch_op.drop_column('greet_status')
        batch_op.drop_column('boss_id')

    with op.batch_alter_table('jobs') as batch_op:
        batch_op.drop_column('greet_threshold')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('daily_cap')
```

- [ ] **Step 10: config.py 加 F3 配置**

修改 `app/config.py` — 加配置项（与现有 Settings 风格一致）：

```python
    f3_default_greet_threshold: int = 60
    f3_default_daily_cap: int = 1000
    f3_ai_parse_enabled: bool = False
```

- [ ] **Step 11: 写迁移测试（失败）**

创建 `tests/modules/recruit_bot/test_migration_0010.py`：

```python
"""0010 迁移落字段 + UNIQUE(user_id, boss_id)."""
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


@pytest.fixture
def migrated_db(tmp_path):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    return sa.create_engine(url, connect_args={"check_same_thread": False})


def test_users_daily_cap_column(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(users)")).fetchall()
    cols = {r[1]: r for r in info}
    assert "daily_cap" in cols
    assert cols["daily_cap"][4] in ("1000", 1000)  # server_default


def test_jobs_greet_threshold_column(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(jobs)")).fetchall()
    cols = {r[1]: r for r in info}
    assert "greet_threshold" in cols


def test_resumes_boss_fields(migrated_db):
    with migrated_db.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(resumes)")).fetchall()
    cols = {r[1] for r in info}
    assert {"boss_id", "greet_status", "greeted_at"} <= cols


def test_resumes_unique_user_boss(migrated_db):
    with migrated_db.connect() as conn:
        idxs = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()
    names = {r[0] for r in idxs}
    assert "ix_resumes_user_boss" in names


def test_migration_is_reversible(tmp_path):
    db = tmp_path / "t.db"
    url = f"sqlite:///{db}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    command.downgrade(cfg, "0009")
    eng = sa.create_engine(url, connect_args={"check_same_thread": False})
    with eng.connect() as conn:
        info = conn.execute(sa.text("PRAGMA table_info(resumes)")).fetchall()
    cols = {r[1] for r in info}
    assert "boss_id" not in cols
    assert "greet_status" not in cols
```

- [ ] **Step 12: 运行迁移测试**

```bash
python -m pytest tests/modules/recruit_bot/test_migration_0010.py -v
```

预期：5 passed。

- [ ] **Step 13: 完整 pytest 确认无回归**

```bash
python -m pytest tests/ -q --ignore=tests/e2e
```

预期：`378 passed / 7 failed`（373 base + 7 new schemas + 5 new migration - 1? let me recount: 7+5=12. 373+12=385）。实际跑后写下实际数字：`____ passed / 7 failed`。

- [ ] **Step 14: Commit T0**

```bash
git add app/modules/auth/models.py app/modules/screening/models.py app/modules/resume/models.py app/config.py migrations/versions/0010_f3_recruit_bot_fields.py tests/modules/recruit_bot/test_migration_0010.py
git commit -m "feat(f3-T0): migration 0010 + daily_cap/greet_threshold/boss fields + 5 migration tests"
```

---

## Task 1: content.js DOM selectors 常量文件

**Files:**
- Create: `edge_extension/f3_selectors.js`
- Modify: `edge_extension/manifest.json`

背景：spec §5.2 已 live 观察 Boss 推荐页，但具体 CSS class 名 Boss 随时可能变。集中成常量文件，未来一处改。

- [ ] **Step 1: 创建 f3_selectors.js**

创建 `edge_extension/f3_selectors.js`：

```javascript
// F3 Boss 推荐牛人页 DOM selectors — 集中常量, 未来 DOM 变只改此处
// 2026-04-21 MCP 登入实地探查的基础版本; T6 实现时会在真实页面 devtools 里精确化

const F3_SELECTORS = {
  // 页面判定
  PAGE_URL_PATH: '/web/chat/recommend',

  // 顶部岗位选择下拉（Q8 岗位对齐检查用）
  TOP_JOB_DROPDOWN: '.job-select-dropdown, [class*="job-select"], [class*="job-name"]',
  TOP_JOB_TEXT: '.job-select-dropdown .selected-text, [class*="job-select"] span',

  // 候选人卡片容器 — 列表项
  CARD_LIST_CONTAINER: '.geek-recommend-list, .recommend-list, [class*="candidate-list"]',
  CARD_ITEM: '.geek-item, .candidate-item, [class*="recommend-card"]',

  // 单卡片内
  CARD_NAME: '.geek-name, [class*="name"]:not([class*="school-name"])',
  CARD_BASE_INFO: '.geek-base-info, [class*="base-info"]',  // 含年龄/毕业年/学历/活跃状态
  CARD_RECENT_FOCUS: '.geek-expect, [class*="expect"]',     // 最近关注行
  CARD_EDUCATION_ROW: '.geek-edu, [class*="edu-row"]',      // 学历·学校·专业·学位
  CARD_WORK_ROW: '.geek-work, [class*="work-row"]',         // 工作经历简述
  CARD_TAG_ROW: '.geek-tags, [class*="tag-list"]',          // tag 集合
  CARD_TAG_ITEM: '.tag-item, [class*="tag"]',
  CARD_SALARY: '.salary-tag, [class*="salary"]',
  CARD_ACTIVE_STATUS: '.active-status, [class*="active-time"]',

  // 打招呼按钮（list-level, 非 modal）
  CARD_GREET_BTN: '.btn-greet, [class*="greet-btn"], button:contains("打招呼")',
  // 点完后按钮变化标志（T1 实测填准）
  CARD_GREET_BTN_DONE: '.btn-greet.done, [class*="greet-done"]',

  // 风控告警元素 (spec §7.3)
  RISK_CAPTCHA: '.captcha-wrap',
  RISK_VERIFY: '[class*="verify"]',
  RISK_ALERT: '[class*="risk-tip"], [class*="intercept"]',

  // 付费打招呼弹窗（视为风控）
  PAID_GREET_DIALOG: '[class*="pay-dialog"], [class*="upgrade-dialog"]',

  // 风控文案模式（innerText 扫描）
  RISK_TEXT_PATTERNS: [
    '操作过于频繁',
    '请稍后再试',
    '账号异常',
    '人机验证',
    '开通套餐',
    '升级会员',
  ],
};

// 导出给 content.js 用
if (typeof module !== 'undefined') module.exports = { F3_SELECTORS };
```

- [ ] **Step 2: manifest.json 把 f3_selectors.js 加到 content_scripts**

修改 `edge_extension/manifest.json` —— content_scripts 的 js 数组：

```json
  "content_scripts": [
    {
      "matches": ["https://www.zhipin.com/*"],
      "js": ["f3_selectors.js", "content.js"],
      "css": ["styles.css"]
    }
  ],
```

注意 `f3_selectors.js` 必须在 `content.js` 之前，这样 content.js 可以读全局变量 `F3_SELECTORS`。

- [ ] **Step 3: Commit T1**

```bash
git add edge_extension/f3_selectors.js edge_extension/manifest.json
git commit -m "feat(f3-T1): centralize Boss recommend page DOM selectors"
```

---

## Task 2: service.upsert_resume_by_boss_id

**Files:**
- Create: `app/modules/recruit_bot/service.py`（部分内容）
- Create: `tests/modules/recruit_bot/test_upsert_resume.py`

- [ ] **Step 1: 写 upsert 测试（失败）**

创建 `tests/modules/recruit_bot/test_upsert_resume.py`：

```python
"""upsert_resume_by_boss_id — UNIQUE(user_id, boss_id) 幂等."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    session = factory()
    yield session
    session.close()


def _mk_candidate(boss_id="xyz001", name="张三"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name=name, boss_id=boss_id, age=28,
        education="本科", school="XX 大学", major="计算机",
        intended_job="后端", work_years=3,
        skill_tags=["Python", "Redis"],
        raw_text="full text",
    )


def test_upsert_creates_new_resume(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    assert r.id > 0
    assert r.name == "张三"
    assert r.boss_id == "xyz001"
    assert r.user_id == 1
    assert r.source == "boss_zhipin"
    assert r.skills == "Python,Redis"
    assert r.greet_status == "none"


def test_upsert_idempotent_same_boss_id(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r2 = upsert_resume_by_boss_id(
        db, user_id=1, candidate=_mk_candidate(name="张三改名"),
    )
    assert r1.id == r2.id
    assert r2.name == "张三改名"  # 字段更新


def test_upsert_different_users_different_rows(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r2 = upsert_resume_by_boss_id(db, user_id=2, candidate=_mk_candidate())
    assert r1.id != r2.id


def test_upsert_does_not_clobber_greet_status(db):
    """既有 greet_status='greeted' 的 resume 再 upsert 不把状态重置."""
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    from app.modules.resume.models import Resume
    r1 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate())
    r1.greet_status = "greeted"
    db.commit()
    r2 = upsert_resume_by_boss_id(db, user_id=1, candidate=_mk_candidate(name="新名"))
    assert r2.greet_status == "greeted"  # 未被清


def test_upsert_skill_tags_csv_conversion(db):
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    c = ScrapedCandidate(
        name="李四", boss_id="zzz",
        skill_tags=["Java", "Spring", "Redis"],
    )
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    assert r.skills == "Java,Spring,Redis"


def test_upsert_raw_text_includes_all_fields(db):
    """raw_text 回填成调试用的 summary, 所有字段拼接."""
    from app.modules.recruit_bot.service import upsert_resume_by_boss_id
    c = _mk_candidate()
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    assert "Python" in r.raw_text
    assert "张三" in r.raw_text or "后端" in r.raw_text
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
python -m pytest tests/modules/recruit_bot/test_upsert_resume.py -v
```

预期：ImportError from service.py not existing.

- [ ] **Step 3: 实现 upsert_resume_by_boss_id**

创建 `app/modules/recruit_bot/service.py`：

```python
"""F3 RecruitBot 核心服务 — 候选人 upsert / 决策 / 打招呼记录 / 配额."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.modules.resume.models import Resume

if TYPE_CHECKING:
    from app.modules.recruit_bot.schemas import ScrapedCandidate


def _summarize_raw_text(c: "ScrapedCandidate") -> str:
    """拼接所有 scraped 字段为调试 summary."""
    parts = [
        f"姓名:{c.name}",
        f"boss_id:{c.boss_id}",
        f"年龄:{c.age or ''}",
        f"学历:{c.education}",
        f"毕业年:{c.grad_year or ''}",
        f"工作年:{c.work_years}",
        f"学校:{c.school}",
        f"专业:{c.major}",
        f"意向:{c.intended_job}",
        f"技能:{','.join(c.skill_tags)}",
        f"院校tag:{','.join(c.school_tier_tags)}",
        f"排名tag:{','.join(c.ranking_tags)}",
        f"期望薪资:{c.expected_salary}",
        f"活跃:{c.active_status}",
        f"推荐理由:{c.recommendation_reason}",
        f"最近工作:{c.latest_work_brief}",
    ]
    return " | ".join(parts)


def upsert_resume_by_boss_id(
    db: Session, user_id: int, candidate: "ScrapedCandidate",
) -> Resume:
    """按 (user_id, boss_id) 查找或新建 Resume 行.

    已存在时更新非状态字段（保留 status / greet_status / greeted_at / ai_* 不动）.
    """
    existing = (
        db.query(Resume)
        .filter(Resume.user_id == user_id, Resume.boss_id == candidate.boss_id)
        .first()
    )
    now = datetime.now(timezone.utc)
    skills_csv = ",".join(candidate.skill_tags)
    raw_text = candidate.raw_text or _summarize_raw_text(candidate)

    if existing:
        existing.name = candidate.name
        existing.education = candidate.education or existing.education
        existing.work_years = candidate.work_years or existing.work_years
        existing.job_intention = candidate.intended_job or existing.job_intention
        existing.skills = skills_csv or existing.skills
        existing.work_experience = (
            candidate.latest_work_brief or existing.work_experience
        )
        existing.raw_text = raw_text
        existing.updated_at = now
        # 故意不动: status, greet_status, greeted_at, ai_parsed, ai_score, ai_summary
        db.commit()
        db.refresh(existing)
        return existing

    r = Resume(
        user_id=user_id,
        name=candidate.name,
        boss_id=candidate.boss_id,
        education=candidate.education,
        work_years=candidate.work_years,
        job_intention=candidate.intended_job,
        skills=skills_csv,
        work_experience=candidate.latest_work_brief,
        source="boss_zhipin",
        raw_text=raw_text,
        status="passed",
        greet_status="none",
        created_at=now,
        updated_at=now,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
python -m pytest tests/modules/recruit_bot/test_upsert_resume.py -v
```

预期：6 passed。

- [ ] **Step 5: Commit T2**

```bash
git add app/modules/recruit_bot/service.py tests/modules/recruit_bot/test_upsert_resume.py
git commit -m "feat(f3-T2): upsert_resume_by_boss_id service + 6 idempotency tests"
```

---

## Task 3: service.evaluate_and_record

**Files:**
- Modify: `app/modules/recruit_bot/service.py`
- Create: `tests/modules/recruit_bot/test_evaluate_and_record.py`

- [ ] **Step 1: 写 evaluate 测试（失败）**

创建 `tests/modules/recruit_bot/test_evaluate_and_record.py`：

```python
"""evaluate_and_record — 核心决策."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)
    session = factory()

    from app.modules.auth.models import User
    u = User(username="hr1", password_hash="x", daily_cap=1000)
    session.add(u)
    session.commit()

    yield session
    session.close()


def _mk_job(db, user_id=1, threshold=60, with_competency=True):
    from app.modules.screening.models import Job
    comp = {
        "schema_version": 1,
        "hard_skills": [
            {"name": "Python", "weight": 9, "must_have": True},
            {"name": "Redis", "weight": 5, "must_have": False},
        ],
        "soft_skills": [],
        "experience": {"years_min": 2, "years_max": 5, "industries": []},
        "education": {"min_level": "本科"},
        "job_level": "",
        "bonus_items": [], "exclusions": [], "assessment_dimensions": [],
        "source_jd_hash": "h", "extracted_at": "2026-04-21T00:00:00Z",
    } if with_competency else None
    j = Job(
        user_id=user_id, title="后端", jd_text="招 Python",
        competency_model=comp,
        competency_model_status="approved" if with_competency else "none",
        greet_threshold=threshold,
    )
    db.add(j); db.commit(); db.refresh(j)
    return j


def _mk_candidate(boss_id="b1", name="张三", skills=None, work_years=3, education="本科"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name=name, boss_id=boss_id, age=28,
        education=education, school="XX 大学", major="CS",
        intended_job="后端", work_years=work_years,
        skill_tags=skills or ["Python", "Redis"],
    )


@pytest.mark.asyncio
async def test_evaluate_should_greet_high_score(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    job = _mk_job(db, threshold=30)
    c = _mk_candidate()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "should_greet"
    assert dec.resume_id is not None
    assert dec.score is not None
    assert dec.score >= 30


@pytest.mark.asyncio
async def test_evaluate_rejected_low_score(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.modules.resume.models import Resume
    job = _mk_job(db, threshold=95)
    c = _mk_candidate()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "rejected_low_score"
    r = db.query(Resume).filter_by(id=dec.resume_id).first()
    assert r.status == "rejected"
    assert str(dec.score) in r.reject_reason


@pytest.mark.asyncio
async def test_evaluate_skipped_already_greeted(db):
    from app.modules.recruit_bot.service import evaluate_and_record, upsert_resume_by_boss_id
    job = _mk_job(db, threshold=30)
    c = _mk_candidate()
    r = upsert_resume_by_boss_id(db, user_id=1, candidate=c)
    r.greet_status = "greeted"
    db.commit()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "skipped_already_greeted"
    assert dec.resume_id == r.id


@pytest.mark.asyncio
async def test_evaluate_blocked_daily_cap(db):
    """cap=1 且已打过 1 次 → 返 blocked_daily_cap."""
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.modules.auth.models import User
    from app.modules.resume.models import Resume
    from datetime import datetime, timezone
    user = db.query(User).filter_by(id=1).first()
    user.daily_cap = 1
    prev = Resume(
        user_id=1, name="prev", boss_id="other",
        greet_status="greeted",
        greeted_at=datetime.now(timezone.utc),
        source="boss_zhipin",
    )
    db.add(prev); db.commit()

    job = _mk_job(db, threshold=30)
    c = _mk_candidate(boss_id="new_cand")
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "blocked_daily_cap"


@pytest.mark.asyncio
async def test_evaluate_error_no_competency(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    job = _mk_job(db, with_competency=False)
    c = _mk_candidate()
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    assert dec.decision == "error_no_competency"


@pytest.mark.asyncio
async def test_evaluate_writes_audit_events(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.core.audit.models import AuditEvent
    job = _mk_job(db, threshold=30)
    c = _mk_candidate()
    await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
    events = db.query(AuditEvent).filter(AuditEvent.f_stage == "F3_evaluate").all()
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_evaluate_foreign_job_raises(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    job = _mk_job(db, user_id=999)  # 另一个用户的 job
    c = _mk_candidate()
    with pytest.raises(ValueError, match="not found"):
        await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=c)
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
python -m pytest tests/modules/recruit_bot/test_evaluate_and_record.py -v
```

预期：ImportError evaluate_and_record not defined.

- [ ] **Step 3: 实现 evaluate_and_record + get_daily_usage (内部用)**

追加到 `app/modules/recruit_bot/service.py` 末尾：

```python
import logging
from app.core.audit.logger import log_event
from app.modules.auth.models import User
from app.modules.recruit_bot.schemas import RecruitDecision, UsageInfo
from app.modules.screening.models import Job
from app.modules.matching.service import MatchingService

logger = logging.getLogger(__name__)


def _today_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_daily_usage(db: Session, user_id: int) -> UsageInfo:
    """返该 user 今日已打招呼次数 + 配额."""
    user = db.query(User).filter(User.id == user_id).first()
    cap = user.daily_cap if user else 1000
    start = _today_start_utc()
    used = (
        db.query(Resume)
        .filter(
            Resume.user_id == user_id,
            Resume.greet_status == "greeted",
            Resume.greeted_at >= start,
        )
        .count()
    )
    return UsageInfo(used=used, cap=cap, remaining=max(0, cap - used))


async def evaluate_and_record(
    db: Session, user_id: int, job_id: int,
    candidate: "ScrapedCandidate",
) -> RecruitDecision:
    """核心决策: daily_cap → upsert → 已greeted skip → F2 score → threshold → record."""
    # 1. daily_cap
    usage = get_daily_usage(db, user_id)
    if usage.remaining <= 0:
        log_event(
            f_stage="F3_evaluate", action="blocked_daily_cap",
            entity_type="job", entity_id=job_id,
            input_payload={"boss_id": candidate.boss_id, "usage": usage.model_dump()},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="blocked_daily_cap",
            reason=f"今日已打 {usage.used}/{usage.cap}",
        )

    # 2. job 归属 + competency_model
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == user_id)
        .first()
    )
    if not job:
        raise ValueError(f"job {job_id} not found for user {user_id}")
    if not job.competency_model:
        log_event(
            f_stage="F3_evaluate", action="error_no_competency",
            entity_type="job", entity_id=job_id,
            input_payload={"boss_id": candidate.boss_id},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="error_no_competency",
            reason=f"job {job_id} 能力模型未生成",
        )

    # 3. upsert resume
    resume = upsert_resume_by_boss_id(db, user_id=user_id, candidate=candidate)

    # 4. 已 greeted 跳过
    if resume.greet_status == "greeted":
        log_event(
            f_stage="F3_evaluate", action="skipped_already_greeted",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="skipped_already_greeted",
            resume_id=resume.id,
            reason="历史已打过招呼",
        )

    # 5. F2 匹配打分
    svc = MatchingService(db)
    try:
        result = await svc.score_pair(resume.id, job.id, triggered_by="F3")
    except Exception as e:
        logger.exception(f"F3 score_pair failed: {e}")
        return RecruitDecision(
            decision="error_no_competency",
            resume_id=resume.id,
            reason=f"打分异常: {e}",
        )

    threshold = job.greet_threshold or 60
    score = int(result.total_score)

    # 6. 阈值判定 + 更新 resume
    if score >= threshold:
        resume.status = "passed"
        resume.greet_status = "pending_greet"
        resume.updated_at = datetime.now(timezone.utc)
        db.commit()
        log_event(
            f_stage="F3_evaluate", action="should_greet",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id, "score": score, "threshold": threshold},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="should_greet",
            resume_id=resume.id, score=score, threshold=threshold,
            reason=f"分 {score} ≥ 阈值 {threshold}",
        )
    else:
        resume.status = "rejected"
        resume.reject_reason = f"F3 分{score}低于阈值{threshold}"
        resume.updated_at = datetime.now(timezone.utc)
        db.commit()
        log_event(
            f_stage="F3_evaluate", action="rejected_low_score",
            entity_type="resume", entity_id=resume.id,
            input_payload={"boss_id": candidate.boss_id, "score": score, "threshold": threshold},
            reviewer_id=user_id,
        )
        return RecruitDecision(
            decision="rejected_low_score",
            resume_id=resume.id, score=score, threshold=threshold,
            reason=f"分 {score} < 阈值 {threshold}",
        )
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
python -m pytest tests/modules/recruit_bot/test_evaluate_and_record.py -v
```

预期：7 passed。

若某些子测试 score 不符合预期（F2 scorer 基于 bge-m3 可能返不同值），**不要改 score 断言死数**。改为 `>= 30` / `<= 95` 这类阈值断言。

- [ ] **Step 5: Commit T3**

```bash
git add app/modules/recruit_bot/service.py tests/modules/recruit_bot/test_evaluate_and_record.py
git commit -m "feat(f3-T3): evaluate_and_record with F2 scoring + 7 decision tests"
```

---

## Task 4: service.record_greet_sent + 深化 get_daily_usage

**Files:**
- Modify: `app/modules/recruit_bot/service.py`
- Create: `tests/modules/recruit_bot/test_record_greet.py`
- Create: `tests/modules/recruit_bot/test_daily_usage.py`

- [ ] **Step 1: 写 record_greet 测试**

创建 `tests/modules/recruit_bot/test_record_greet.py`：

```python
"""record_greet_sent — 幂等 + 审计."""
import pytest
from datetime import datetime, timezone
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)
    session = factory()
    yield session
    session.close()


def _mk_resume(db, user_id=1, boss_id="b1", greet_status="pending_greet"):
    from app.modules.resume.models import Resume
    r = Resume(
        user_id=user_id, name="张三", boss_id=boss_id,
        source="boss_zhipin", greet_status=greet_status,
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def test_record_greet_success(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.modules.resume.models import Resume
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=True)
    db.expire(r); r = db.query(Resume).filter_by(id=r.id).first()
    assert r.greet_status == "greeted"
    assert r.greeted_at is not None


def test_record_greet_failed(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.modules.resume.models import Resume
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=False, error_msg="button_not_found")
    db.expire(r); r = db.query(Resume).filter_by(id=r.id).first()
    assert r.greet_status == "failed"
    assert r.greeted_at is None


def test_record_greet_idempotent_on_already_greeted(db):
    """再次 record success 不改 greeted_at（锁定首次时间）."""
    from app.modules.recruit_bot.service import record_greet_sent
    from app.modules.resume.models import Resume
    r = _mk_resume(db, greet_status="greeted")
    r.greeted_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    record_greet_sent(db, user_id=1, resume_id=r.id, success=True)
    db.expire(r); r = db.query(Resume).filter_by(id=r.id).first()
    assert r.greet_status == "greeted"
    assert r.greeted_at.year == 2020  # 不变


def test_record_greet_foreign_resume_raises(db):
    from app.modules.recruit_bot.service import record_greet_sent
    r = _mk_resume(db, user_id=999)
    with pytest.raises(ValueError):
        record_greet_sent(db, user_id=1, resume_id=r.id, success=True)


def test_record_greet_writes_audit_success(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.core.audit.models import AuditEvent
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=True)
    events = db.query(AuditEvent).filter(AuditEvent.f_stage == "F3_greet_sent").all()
    assert len(events) >= 1


def test_record_greet_writes_audit_failed_with_error(db):
    from app.modules.recruit_bot.service import record_greet_sent
    from app.core.audit.models import AuditEvent
    r = _mk_resume(db)
    record_greet_sent(db, user_id=1, resume_id=r.id, success=False, error_msg="risk_detected")
    events = db.query(AuditEvent).filter(AuditEvent.f_stage == "F3_greet_failed").all()
    assert len(events) >= 1
    ev = events[0]
    payload = ev.output_payload or {}
    assert "risk_detected" in str(payload)
```

- [ ] **Step 2: 实现 record_greet_sent**

追加到 `app/modules/recruit_bot/service.py`：

```python
def record_greet_sent(
    db: Session, user_id: int, resume_id: int,
    success: bool, error_msg: str = "",
) -> None:
    """记录打招呼动作结果. 幂等: 已 greeted 的 resume 再调 success=True 不动 greeted_at."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == user_id)
        .first()
    )
    if not resume:
        raise ValueError(f"resume {resume_id} not found for user {user_id}")

    now = datetime.now(timezone.utc)

    if success:
        if resume.greet_status != "greeted":
            resume.greet_status = "greeted"
            resume.greeted_at = now
            resume.updated_at = now
            db.commit()
        log_event(
            f_stage="F3_greet_sent", action="greet_sent",
            entity_type="resume", entity_id=resume_id,
            input_payload={"boss_id": resume.boss_id},
            reviewer_id=user_id,
        )
    else:
        resume.greet_status = "failed"
        resume.updated_at = now
        db.commit()
        log_event(
            f_stage="F3_greet_failed", action="greet_failed",
            entity_type="resume", entity_id=resume_id,
            input_payload={"boss_id": resume.boss_id},
            output_payload={"error": error_msg},
            reviewer_id=user_id,
        )
```

- [ ] **Step 3: 写 daily_usage 测试**

创建 `tests/modules/recruit_bot/test_daily_usage.py`：

```python
"""get_daily_usage — per-user 今日打招呼计数."""
import pytest
from datetime import datetime, timezone, timedelta
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    session = factory()
    from app.modules.auth.models import User
    session.add_all([
        User(username="a", password_hash="x", daily_cap=100),
        User(username="b", password_hash="x", daily_cap=50),
    ])
    session.commit()
    yield session
    session.close()


def _mk_greeted(db, user_id, boss_id, greeted_at):
    from app.modules.resume.models import Resume
    db.add(Resume(
        user_id=user_id, name=f"n{boss_id}", boss_id=boss_id,
        source="boss_zhipin", greet_status="greeted",
        greeted_at=greeted_at,
    ))
    db.commit()


def test_daily_usage_zero_initially(db):
    from app.modules.recruit_bot.service import get_daily_usage
    u = get_daily_usage(db, user_id=1)
    assert u.used == 0
    assert u.cap == 100
    assert u.remaining == 100


def test_daily_usage_counts_today_only(db):
    from app.modules.recruit_bot.service import get_daily_usage
    now = datetime.now(timezone.utc)
    _mk_greeted(db, 1, "today_1", now)
    _mk_greeted(db, 1, "today_2", now)
    _mk_greeted(db, 1, "yesterday", now - timedelta(days=1, hours=1))
    u = get_daily_usage(db, user_id=1)
    assert u.used == 2
    assert u.remaining == 98


def test_daily_usage_per_user_isolated(db):
    from app.modules.recruit_bot.service import get_daily_usage
    now = datetime.now(timezone.utc)
    _mk_greeted(db, 1, "u1_x", now)
    _mk_greeted(db, 2, "u2_x", now)
    _mk_greeted(db, 2, "u2_y", now)
    ua = get_daily_usage(db, user_id=1)
    ub = get_daily_usage(db, user_id=2)
    assert ua.used == 1
    assert ub.used == 2
    assert ub.cap == 50


def test_daily_usage_ignores_non_greeted(db):
    from app.modules.recruit_bot.service import get_daily_usage
    from app.modules.resume.models import Resume
    now = datetime.now(timezone.utc)
    db.add_all([
        Resume(user_id=1, name="a", boss_id="a", source="boss_zhipin",
               greet_status="pending_greet", greeted_at=now),
        Resume(user_id=1, name="b", boss_id="b", source="boss_zhipin",
               greet_status="failed", greeted_at=now),
    ])
    db.commit()
    u = get_daily_usage(db, user_id=1)
    assert u.used == 0
```

- [ ] **Step 4: 运行全部 service 测试**

```bash
python -m pytest tests/modules/recruit_bot/test_record_greet.py tests/modules/recruit_bot/test_daily_usage.py -v
```

预期：6 + 4 = 10 passed。

- [ ] **Step 5: Commit T4**

```bash
git add app/modules/recruit_bot/service.py tests/modules/recruit_bot/test_record_greet.py tests/modules/recruit_bot/test_daily_usage.py
git commit -m "feat(f3-T4): record_greet_sent + get_daily_usage + 10 tests"
```

---

## Task 5: router.py — 4 个端点

**Files:**
- Create: `app/modules/recruit_bot/router.py`
- Modify: `app/main.py`
- Create: `tests/modules/recruit_bot/test_router_evaluate.py`
- Create: `tests/modules/recruit_bot/test_router_record_greet.py`
- Create: `tests/modules/recruit_bot/test_router_daily_usage.py`

- [ ] **Step 1: 写 router 测试（失败）— evaluate**

创建 `tests/modules/recruit_bot/test_router_evaluate.py`：

```python
"""POST /api/recruit/evaluate_and_record."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)

    session = factory()
    from app.modules.auth.models import User
    from app.modules.screening.models import Job
    u = User(username="hr1", password_hash="x", daily_cap=1000); session.add(u); session.commit()
    j = Job(
        user_id=u.id, title="后端", jd_text="招 Python",
        competency_model={
            "schema_version": 1,
            "hard_skills": [{"name":"Python","weight":9,"must_have":True}],
            "soft_skills":[],"experience":{"years_min":2,"years_max":5,"industries":[]},
            "education":{"min_level":"本科"},"job_level":"","bonus_items":[],
            "exclusions":[],"assessment_dimensions":[],
            "source_jd_hash":"h","extracted_at":"2026-04-21T00:00:00Z",
        },
        competency_model_status="approved", greet_threshold=30,
    )
    session.add(j); session.commit()
    session.close()

    from app.main import app
    with TestClient(app) as c:
        yield c, j.id, u.id


def _body(job_id, boss_id="b1", name="张三"):
    return {
        "job_id": job_id,
        "candidate": {
            "name": name, "boss_id": boss_id,
            "education": "本科", "work_years": 3,
            "intended_job": "后端", "skill_tags": ["Python"],
        },
    }


def test_evaluate_requires_auth(tmp_path, monkeypatch):
    import os
    from fastapi.testclient import TestClient
    monkeypatch.delenv("AGENTICHR_TEST_BYPASS_AUTH", raising=False)
    from app.main import app
    c = TestClient(app)
    # PYTEST_CURRENT_TEST is set by pytest, but bypass env is off
    r = c.post("/api/recruit/evaluate_and_record", json={"job_id": 1, "candidate": {"name":"a","boss_id":"b"}})
    assert r.status_code == 401


def test_evaluate_returns_should_greet(client):
    c, jid, uid = client
    r = c.post("/api/recruit/evaluate_and_record", json=_body(jid))
    assert r.status_code == 200
    d = r.json()
    assert d["decision"] == "should_greet"
    assert d["resume_id"] is not None
    assert d["score"] >= 30


def test_evaluate_rejects_foreign_job(client):
    c, jid, uid = client
    r = c.post("/api/recruit/evaluate_and_record", json=_body(99999))
    assert r.status_code == 404


def test_evaluate_validates_missing_boss_id(client):
    c, jid, uid = client
    body = _body(jid); body["candidate"]["boss_id"] = ""
    r = c.post("/api/recruit/evaluate_and_record", json=body)
    assert r.status_code == 422
```

- [ ] **Step 2: 写 router 测试 — record_greet**

创建 `tests/modules/recruit_bot/test_router_record_greet.py`：

```python
"""POST /api/recruit/record-greet."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)

    session = factory()
    from app.modules.auth.models import User
    from app.modules.resume.models import Resume
    u = User(username="hr1", password_hash="x"); session.add(u); session.commit()
    r = Resume(user_id=u.id, name="张三", boss_id="b1", source="boss_zhipin",
               greet_status="pending_greet")
    session.add(r); session.commit()
    rid = r.id
    session.close()

    from app.main import app
    with TestClient(app) as c:
        yield c, rid


def test_record_greet_success_updates_status(client):
    c, rid = client
    r = c.post("/api/recruit/record-greet",
               json={"resume_id": rid, "success": True})
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"


def test_record_greet_failed_writes_error(client):
    c, rid = client
    r = c.post("/api/recruit/record-greet",
               json={"resume_id": rid, "success": False, "error_msg": "risk_control_detected"})
    assert r.status_code == 200


def test_record_greet_foreign_resume_404(client):
    c, rid = client
    r = c.post("/api/recruit/record-greet",
               json={"resume_id": 99999, "success": True})
    assert r.status_code == 404
```

- [ ] **Step 3: 写 router 测试 — daily_usage + daily_cap**

创建 `tests/modules/recruit_bot/test_router_daily_usage.py`：

```python
"""GET /api/recruit/daily-usage + PUT /api/recruit/daily-cap."""
import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    session = factory()
    from app.modules.auth.models import User
    u = User(username="hr1", password_hash="x", daily_cap=500); session.add(u); session.commit()
    session.close()
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_daily_usage_initial(client):
    r = client.get("/api/recruit/daily-usage")
    assert r.status_code == 200
    d = r.json()
    assert d["used"] == 0
    assert d["cap"] == 500
    assert d["remaining"] == 500


def test_daily_cap_update(client):
    r = client.put("/api/recruit/daily-cap", json={"cap": 2000})
    assert r.status_code == 200
    assert r.json()["cap"] == 2000
    r2 = client.get("/api/recruit/daily-usage")
    assert r2.json()["cap"] == 2000


def test_daily_cap_rejects_negative(client):
    r = client.put("/api/recruit/daily-cap", json={"cap": -1})
    assert r.status_code == 422


def test_daily_cap_rejects_too_large(client):
    r = client.put("/api/recruit/daily-cap", json={"cap": 10001})
    assert r.status_code == 422
```

- [ ] **Step 4: 运行测试确认 fail**

```bash
python -m pytest tests/modules/recruit_bot/test_router_evaluate.py tests/modules/recruit_bot/test_router_record_greet.py tests/modules/recruit_bot/test_router_daily_usage.py -v
```

预期：全 fail（router 不存在）。

- [ ] **Step 5: 写 router.py**

创建 `app/modules/recruit_bot/router.py`：

```python
"""F3 RecruitBot HTTP API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.deps import get_current_user_id
from app.modules.auth.models import User
from app.modules.recruit_bot.schemas import (
    DailyCapUpdateRequest,
    GreetRecordRequest,
    RecruitDecision,
    RecruitEvaluateRequest,
    UsageInfo,
)
from app.modules.recruit_bot.service import (
    evaluate_and_record,
    get_daily_usage,
    record_greet_sent,
)

router = APIRouter(prefix="/api/recruit", tags=["recruit"])


@router.post("/evaluate_and_record", response_model=RecruitDecision)
async def evaluate_endpoint(
    body: RecruitEvaluateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> RecruitDecision:
    try:
        return await evaluate_and_record(
            db, user_id=user_id,
            job_id=body.job_id, candidate=body.candidate,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/record-greet")
def record_greet_endpoint(
    body: GreetRecordRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    try:
        record_greet_sent(
            db, user_id=user_id, resume_id=body.resume_id,
            success=body.success, error_msg=body.error_msg,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "recorded"}


@router.get("/daily-usage", response_model=UsageInfo)
def daily_usage_endpoint(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> UsageInfo:
    return get_daily_usage(db, user_id)


@router.put("/daily-cap")
def daily_cap_update_endpoint(
    body: DailyCapUpdateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    user.daily_cap = body.cap
    db.commit()
    return {"cap": body.cap}
```

- [ ] **Step 6: main.py 注册 router**

在 `app/main.py` 的现有 `include_router` 列表中加：

```python
from app.modules.recruit_bot.router import router as recruit_router
app.include_router(recruit_router)
```

- [ ] **Step 7: 运行 router 测试确认 pass**

```bash
python -m pytest tests/modules/recruit_bot/test_router_evaluate.py tests/modules/recruit_bot/test_router_record_greet.py tests/modules/recruit_bot/test_router_daily_usage.py -v
```

预期：4 + 3 + 4 = 11 passed。若 auth test 不 fail，检查 `AGENTICHR_TEST_BYPASS_AUTH` 删除逻辑。

- [ ] **Step 8: 全量回归**

```bash
python -m pytest tests/ -q --ignore=tests/e2e
```

预期：大约 `395 passed / 7 failed`（373 base + 7 schemas + 5 migration + 6 upsert + 7 evaluate + 6 record_greet + 4 daily_usage + 11 router - 小误差。记实际数字）。

- [ ] **Step 9: Commit T5**

```bash
git add app/modules/recruit_bot/router.py app/main.py tests/modules/recruit_bot/test_router_evaluate.py tests/modules/recruit_bot/test_router_record_greet.py tests/modules/recruit_bot/test_router_daily_usage.py
git commit -m "feat(f3-T5): recruit_bot 4 endpoints + 11 router tests"
```

---

## Task 6: content.js — scrapeRecommendCard + simulateHumanClick + detectRiskControl

**Files:**
- Modify: `edge_extension/content.js`

注意：扩展的 JS 代码无 Node 测试基建（现 codebase 没 Jest 配置）。依赖 T10 手工 E2E 验证。

- [ ] **Step 1: 加 F3 util — simulateHumanClick**

在 `edge_extension/content.js` **末尾**（所有现有函数后）追加 F3 工具模块。保留现 autoGreet（chat 页那个）不动。

```javascript
// ════════════════════════════════════════════════════════════════════
// F3 工具 — 反检测人类式操作
// ════════════════════════════════════════════════════════════════════

/**
 * 人类式点击: scrollIntoView + mouseover → mousedown → mouseup → click
 * spec §7.2 反检测要求.
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
 * 检测风控告警. 命中返 true + halt 主循环.
 * spec §7.3.
 */
function detectRiskControl() {
  // DOM element 扫描
  const riskSelectors = [
    F3_SELECTORS.RISK_CAPTCHA,
    F3_SELECTORS.RISK_VERIFY,
    F3_SELECTORS.RISK_ALERT,
    F3_SELECTORS.PAID_GREET_DIALOG,
  ];
  for (const sel of riskSelectors) {
    const el = document.querySelector(sel);
    if (el && el.offsetParent !== null) {
      return { detected: true, source: `selector:${sel}` };
    }
  }
  // 文案扫描
  const bodyText = document.body?.innerText || '';
  for (const pattern of F3_SELECTORS.RISK_TEXT_PATTERNS) {
    if (bodyText.includes(pattern)) {
      return { detected: true, source: `text:${pattern}` };
    }
  }
  return { detected: false };
}
```

- [ ] **Step 2: 加 scrapeRecommendCard**

继续追加：

```javascript
/**
 * 从 Boss 推荐牛人 list 卡片抠字段. LIST-only (spec §5.2).
 * 返回 ScrapedCandidate-shaped plain object.
 */
function scrapeRecommendCard(cardEl) {
  if (!cardEl) return null;

  const bossId = cardEl.getAttribute('data-id')
    || cardEl.getAttribute('data-geek-id')
    || cardEl.querySelector('a[href*="geek"]')?.href?.match(/geek=([^&]+)/)?.[1]
    || '';
  if (!bossId) return null;

  const name = cardEl.querySelector(F3_SELECTORS.CARD_NAME)?.textContent?.trim() || '';
  if (!name) return null;

  // 基础信息行: 年龄 / 毕业年 / 学历 / 活跃状态, 分 span 或靠 | 分隔
  const baseText = cardEl.querySelector(F3_SELECTORS.CARD_BASE_INFO)?.textContent || '';
  const age = parseInt(baseText.match(/(\d+)岁/)?.[1] || '') || null;
  // 毕业年: "27年应届生" → 2027
  const gradMatch = baseText.match(/(\d{2})年(应届生|毕业)/);
  const gradYear = gradMatch ? (2000 + parseInt(gradMatch[1])) : null;
  const eduMatch = baseText.match(/博士|硕士|研究生|本科|学士|大专|专科|高中|中专|MBA/);
  const education = normEdu(eduMatch?.[0] || '');
  const activeStatus =
    (baseText.match(/刚刚活跃|今日活跃|在线|\d+日内活跃/) || [''])[0];

  // 最近关注行 → intended_job
  const focusText = cardEl.querySelector(F3_SELECTORS.CARD_RECENT_FOCUS)?.textContent || '';
  const intendedJob = (focusText.match(/·\s*([^·]+?)(\s*\(|\s*·|$)/) || [,''])[1].trim();

  // 学历行 → school + major
  const eduRow = cardEl.querySelector(F3_SELECTORS.CARD_EDUCATION_ROW)?.textContent || '';
  const eduParts = eduRow.replace(/^学历/, '').split('·').map(s => s.trim()).filter(Boolean);
  const school = eduParts[0] || '';
  const major = eduParts[1] || '';

  // 工作经历简述
  const workRow = cardEl.querySelector(F3_SELECTORS.CARD_WORK_ROW)?.textContent?.trim() || '';
  const latestWorkBrief = workRow === '未填写工作经历' ? '' : workRow;

  // 工作年限: 从 work brief 抠, 无则 0
  const workYears = parseWorkYearsFromBrief(latestWorkBrief);

  // Tags 分类
  const tagEls = cardEl.querySelectorAll(F3_SELECTORS.CARD_TAG_ITEM);
  const skill_tags = [];
  const school_tier_tags = [];
  const ranking_tags = [];
  let recommendation_reason = '';
  tagEls.forEach(t => {
    const txt = t.textContent.trim();
    if (!txt) return;
    if (/^\d+院校$|^985$|^211$|^双一流$/.test(txt)) school_tier_tags.push(txt);
    else if (/专业前\d+%/.test(txt)) ranking_tags.push(txt);
    else if (/来自相似职位|推荐理由/.test(txt)) recommendation_reason = txt;
    else skill_tags.push(txt);
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
  // "2022.01 - 2024.12 XXX · 岗位" → 截止日期 - 起始日期年差
  const m = brief.match(/(\d{4})\.(\d{1,2})\s*-\s*(\d{4})\.(\d{1,2})/);
  if (m) {
    const start = parseInt(m[1]) * 12 + parseInt(m[2]);
    const end = parseInt(m[3]) * 12 + parseInt(m[4]);
    return Math.max(0, Math.round((end - start) / 12));
  }
  return 0;
}

function getBossTopJobTitle() {
  const el = document.querySelector(F3_SELECTORS.TOP_JOB_TEXT);
  if (!el) return '';
  const full = el.textContent.trim();
  // "全栈工程师_北京 400-500元/天" → 取 _ 前
  return full.split('_')[0].split('(')[0].trim();
}
```

- [ ] **Step 3: Commit T6**

```bash
git add edge_extension/content.js
git commit -m "feat(f3-T6): scrapeRecommendCard + simulateHumanClick + detectRiskControl utilities"
```

---

## Task 7: content.js — autoGreetRecommend 主循环

**Files:**
- Modify: `edge_extension/content.js`

- [ ] **Step 1: 加 autoGreetRecommend 主循环**

继续追加到 `edge_extension/content.js` 末尾：

```javascript
// ════════════════════════════════════════════════════════════════════
// F3 主循环 — autoGreetRecommend
// ════════════════════════════════════════════════════════════════════

async function autoGreetRecommend({ jobId, serverUrl, authToken }) {
  LOG.length = 0; _paused = false; _stopped = false; _setRunning(true);
  const stats = { total: 0, greeted: 0, skipped: 0, rejected: 0, failed: 0, blocked: false };
  _setStats(stats);

  try {
    // URL 校验
    if (!location.pathname.includes(F3_SELECTORS.PAGE_URL_PATH)) {
      return { success: false, message: '请先打开 Boss 推荐牛人页', log: LOG };
    }

    // 岗位对齐检查 (Q8 B) — 取 job.title 与 Boss 顶部岗位名比较
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

    // 主循环
    let idx = 0;
    const processedBossIds = new Set();  // Q6 C1 本次运行去重
    let silentMissCount = 0;             // 熔断计数: 按了按钮但 DOM 无反应

    while (!_stopped) {
      await waitIfPaused();

      // 风控检查每轮前
      const risk = detectRiskControl();
      if (risk.detected) {
        stats.blocked = true;
        log(`风控命中: ${risk.source}`);
        return {
          success: false,
          message: `检测到 Boss 风控，已自动停止 (${risk.source})`,
          summary: stats, log: LOG,
        };
      }

      // 拿当前可见卡片 (懒加载靠滚动, 先处理已加载的)
      const cards = Array.from(document.querySelectorAll(F3_SELECTORS.CARD_ITEM));
      if (idx >= cards.length) {
        // 滚动触底尝试加载更多
        window.scrollTo(0, document.body.scrollHeight);
        await sleep(2000);
        const newCards = Array.from(document.querySelectorAll(F3_SELECTORS.CARD_ITEM));
        if (newCards.length === cards.length) {
          log(`列表到底. 处理完 ${idx} 人`);
          break;
        }
        continue; // 重新获取
      }

      const card = cards[idx];
      idx++;

      const scraped = scrapeRecommendCard(card);
      if (!scraped) { stats.skipped++; _setStats(stats); continue; }
      if (processedBossIds.has(scraped.boss_id)) { stats.skipped++; _setStats(stats); continue; }
      processedBossIds.add(scraped.boss_id);

      stats.total++;
      log(`[${idx}] ${scraped.name} (${scraped.boss_id.substring(0,12)})`);

      // 后端决策
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

      // 处理决策
      if (decision.decision === 'blocked_daily_cap') {
        stats.blocked = true;
        log(`每日配额已满: ${decision.reason}`);
        return {
          success: false, message: `今日配额已满 (${decision.reason})`,
          summary: stats, log: LOG,
        };
      }
      if (decision.decision === 'error_no_competency') {
        return {
          success: false, message: `岗位能力模型未生成`,
          summary: stats, log: LOG,
        };
      }
      if (decision.decision === 'skipped_already_greeted') {
        stats.skipped++; log('历史已打过招呼，跳过');
        _setStats(stats);
      }
      else if (decision.decision === 'rejected_low_score') {
        stats.rejected++;
        log(`分 ${decision.score} < 阈值 ${decision.threshold}, 跳过`);
        _setStats(stats);
      }
      else if (decision.decision === 'should_greet') {
        // 找卡片内的打招呼按钮
        const greetBtn = card.querySelector(F3_SELECTORS.CARD_GREET_BTN);
        if (!greetBtn) {
          log('打招呼按钮找不到, 记失败');
          await reportGreetResult(serverUrl, authToken, decision.resume_id, false, 'button_not_found');
          stats.failed++; _setStats(stats); continue;
        }
        try {
          await simulateHumanClick(greetBtn);
          await sleep(1000 + Math.random() * 500);
          // 验证按钮文案 / 状态变化
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

      // 节流: 相邻 2-5s, 每 10 个长停 3-6s
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
  const la = a.length, lb = b.length;
  if (la === 0 || lb === 0) return 0;
  const short = la < lb ? a : b;
  const long = la < lb ? b : a;
  let matches = 0;
  for (const ch of short) {
    if (long.includes(ch)) matches++;
  }
  return matches / Math.max(la, lb);
}
```

- [ ] **Step 2: 消息路由注册 autoGreetRecommend**

在 `edge_extension/content.js` 消息 handler 对象里加入新 action。找到现有的：

```javascript
  const h = {
    collectCurrentResume: () => collectSingle(message.serverUrl, message.authToken || ''),
    batchCollect: () => batchCollect(message.serverUrl, message.authToken || ''),
    autoGreet: () => autoGreet(),
  };
```

改为：

```javascript
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
```

- [ ] **Step 3: Commit T7**

```bash
git add edge_extension/content.js
git commit -m "feat(f3-T7): content.js autoGreetRecommend main loop + rate limit + circuit breaker"
```

---

## Task 8: popup.html + popup.js — F3 section

**Files:**
- Modify: `edge_extension/popup.html`
- Modify: `edge_extension/popup.js`

- [ ] **Step 1: popup.html 加 F3 section**

在 `edge_extension/popup.html` 的"自动打招呼"section **之前**（即"采集当前页面简历"按钮所在 section 上方）插入：

```html
  <div class="section" style="padding-top: 0;">
    <div class="section-title">F3 推荐牛人自动打招呼</div>
    <select id="recruitJobSelect" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px;margin-bottom:8px;">
      <option value="">-- 选择岗位 --</option>
    </select>
    <div style="font-size:12px;color:#666;margin-bottom:8px;">
      今日已打: <span id="usageUsed">0</span> / <span id="usageCap">1000</span>
      <a href="#" id="editCap" style="color:#00b38a;margin-left:8px;">修改</a>
    </div>
    <button class="btn btn-primary" id="btnRecruitStart" style="background:#00b38a;">开始自动打招呼</button>
    <div id="recruitStats" style="font-size:12px;color:#666;margin-top:6px;"></div>
  </div>
```

- [ ] **Step 2: popup.js 加 F3 逻辑**

在 `edge_extension/popup.js` 末尾追加：

```javascript
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
    // 清空现有选项, 保留第一个 placeholder
    recruitJobSelect.innerHTML = '<option value="">-- 选择岗位 --</option>';
    const jobs = Array.isArray(data) ? data : (data.items || []);
    jobs.forEach(j => {
      if (j.competency_model_status !== 'approved') return;  // 只展示已审批
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

// 监听 content.js 推过来的 stats
chrome.storage.onChanged.addListener((changes) => {
  if (changes.recruitStats) {
    const s = changes.recruitStats.newValue || {};
    if (s.total !== undefined) {
      recruitStats.textContent = `进度: 总 ${s.total}, 成 ${s.greeted||0}, 淘 ${s.rejected||0}, 跳 ${s.skipped||0}, 失 ${s.failed||0}`;
    }
  }
});

// DOMContentLoaded 时加载
document.addEventListener('DOMContentLoaded', async () => {
  await loadJobs();
  await loadDailyUsage();
});

editCap.addEventListener('click', (e) => { e.preventDefault(); editDailyCap(); });
btnRecruitStart.addEventListener('click', startAutoRecruit);
recruitJobSelect.addEventListener('change', () => {});
```

同时找到原 `setButtonsDisabled`，把 `btnRecruitStart` 也加进去：

```javascript
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
}
```

- [ ] **Step 3: Commit T8**

```bash
git add edge_extension/popup.html edge_extension/popup.js
git commit -m "feat(f3-T8): popup F3 section — job dropdown + daily cap + start button"
```

---

## Task 9: 集成测试

**Files:**
- Create: `tests/modules/recruit_bot/test_integration.py`

- [ ] **Step 1: 写 5 集成测试**

创建 `tests/modules/recruit_bot/test_integration.py`：

```python
"""F3 端到端后端路径集成测试."""
import pytest
from datetime import datetime, timezone, timedelta
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    url = f"sqlite:///{dbp}"
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0010")
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.engine", engine)
    from app.core.audit import logger as audit_mod
    monkeypatch.setattr(audit_mod, "_session_factory", factory)
    session = factory()
    from app.modules.auth.models import User
    session.add_all([
        User(username="hr1", password_hash="x", daily_cap=1000),
        User(username="hr2", password_hash="x", daily_cap=1000),
    ])
    session.commit()
    yield session
    session.close()


def _mk_job(db, user_id, threshold=30):
    from app.modules.screening.models import Job
    j = Job(
        user_id=user_id, title="后端", jd_text="x",
        competency_model={
            "schema_version": 1,
            "hard_skills": [{"name":"Python","weight":9,"must_have":True}],
            "soft_skills":[],"experience":{"years_min":2,"years_max":5,"industries":[]},
            "education":{"min_level":"本科"},"job_level":"","bonus_items":[],
            "exclusions":[],"assessment_dimensions":[],
            "source_jd_hash":"h","extracted_at":"2026-04-21T00:00:00Z",
        },
        competency_model_status="approved", greet_threshold=threshold,
    )
    db.add(j); db.commit(); db.refresh(j)
    return j


def _mk_cand(boss_id="b1"):
    from app.modules.recruit_bot.schemas import ScrapedCandidate
    return ScrapedCandidate(
        name="张三", boss_id=boss_id, age=28, education="本科",
        school="X 大", major="CS", intended_job="后端",
        work_years=3, skill_tags=["Python", "Redis"],
    )


@pytest.mark.asyncio
async def test_full_pipeline_should_greet_then_record(db):
    from app.modules.recruit_bot.service import (
        evaluate_and_record, record_greet_sent, get_daily_usage,
    )
    from app.modules.resume.models import Resume

    job = _mk_job(db, user_id=1, threshold=30)
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    assert dec.decision == "should_greet"
    assert dec.resume_id is not None

    record_greet_sent(db, user_id=1, resume_id=dec.resume_id, success=True)
    r = db.query(Resume).filter_by(id=dec.resume_id).first()
    assert r.greet_status == "greeted"
    assert r.greeted_at is not None

    usage = get_daily_usage(db, user_id=1)
    assert usage.used == 1


@pytest.mark.asyncio
async def test_full_pipeline_rejected(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    from app.modules.resume.models import Resume
    job = _mk_job(db, user_id=1, threshold=95)
    dec = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    assert dec.decision == "rejected_low_score"
    r = db.query(Resume).filter_by(id=dec.resume_id).first()
    assert r.status == "rejected"
    assert r.greet_status == "none"


@pytest.mark.asyncio
async def test_idempotent_evaluate(db):
    from app.modules.recruit_bot.service import evaluate_and_record
    job = _mk_job(db, user_id=1, threshold=30)
    d1 = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    d2 = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    assert d1.resume_id == d2.resume_id
    assert d1.decision == d2.decision


@pytest.mark.asyncio
async def test_idempotent_record_greet_preserves_timestamp(db):
    from app.modules.recruit_bot.service import (
        evaluate_and_record, record_greet_sent,
    )
    from app.modules.resume.models import Resume
    job = _mk_job(db, user_id=1, threshold=30)
    d = await evaluate_and_record(db, user_id=1, job_id=job.id, candidate=_mk_cand())
    record_greet_sent(db, user_id=1, resume_id=d.resume_id, success=True)
    r1 = db.query(Resume).filter_by(id=d.resume_id).first()
    t1 = r1.greeted_at
    record_greet_sent(db, user_id=1, resume_id=d.resume_id, success=True)
    r2 = db.query(Resume).filter_by(id=d.resume_id).first()
    assert r2.greeted_at == t1


@pytest.mark.asyncio
async def test_cap_across_multi_users(db):
    """user_A 打满 cap → 被 blocked, user_B 不受影响."""
    from app.modules.recruit_bot.service import (
        evaluate_and_record, record_greet_sent,
    )
    from app.modules.auth.models import User
    job_a = _mk_job(db, user_id=1, threshold=30)
    job_b = _mk_job(db, user_id=2, threshold=30)

    ua = db.query(User).filter_by(id=1).first(); ua.daily_cap = 1; db.commit()

    d1 = await evaluate_and_record(db, user_id=1, job_id=job_a.id, candidate=_mk_cand(boss_id="x1"))
    record_greet_sent(db, user_id=1, resume_id=d1.resume_id, success=True)

    d2 = await evaluate_and_record(db, user_id=1, job_id=job_a.id, candidate=_mk_cand(boss_id="x2"))
    assert d2.decision == "blocked_daily_cap"

    # user_B 不受影响
    d3 = await evaluate_and_record(db, user_id=2, job_id=job_b.id, candidate=_mk_cand(boss_id="x3"))
    assert d3.decision == "should_greet"
```

- [ ] **Step 2: 跑集成测试**

```bash
python -m pytest tests/modules/recruit_bot/test_integration.py -v
```

预期：5 passed。

- [ ] **Step 3: 全量回归 + 记录数字**

```bash
python -m pytest tests/ -q --ignore=tests/e2e
```

记录实际结果 —— 期望 `~394 passed / 7 failed`（7 = M2 scheduling pydantic baseline）。

若 passed 数不对：
- 少于预期 → 检查哪些测试 fail 了
- 多于预期 → F2 等其它套件意外多了测试, 非问题但记录差值

- [ ] **Step 4: Commit T9**

```bash
git add tests/modules/recruit_bot/test_integration.py
git commit -m "test(f3-T9): 5 integration tests covering full pipeline + cap isolation"
```

---

## Task 10: 手工 E2E 验证 + CHANGELOG + 最终合并准备

**Files:**
- Modify: `CHANGELOG.md`
- Manual: 实际浏览器测试

- [ ] **Step 1: 手工 E2E — 前 3 项（静态）**

启动开发服务：

```bash
cd D:/libz/AgenticHR && python launcher.py
```

加载扩展：
1. Edge → `edge://extensions` → 开发人员模式 ON → 加载解压缩扩展 → 选 `edge_extension/`
2. 扩展弹出 → 填服务器 URL `http://127.0.0.1:8000` → 测试连接 ✓
3. 登录账号
4. **检查项 1**: popup 打开，"F3 推荐牛人自动打招呼" section 可见，岗位下拉有选项（至少 1 个已 approved 的岗位）
5. **检查项 2**: 选 job → 配额显示 "0 / 1000"（或之前 PUT 后的值）
6. 点击 "修改" → 填新 cap → 显示更新

- [ ] **Step 2: 手工 E2E — 项 3-6（运行时）**

**使用小号 Boss 账号**。打开 `https://www.zhipin.com/web/chat/recommend`。
已登入后回到扩展 popup：

7. **检查项 3**: 点"开始自动打招呼" → Boss 页面开始自动滚动/交互；popup 结果区实时显示进度
8. 运行 3-5 个候选人后, 点 Boss 页面任意处 → 应触发暂停（复用现有 pause 机制）
9. **检查项 4**: 点击 popup 的继续按钮（或复用原 pause 按钮） → 继续运行
10. **检查项 5**: 看到某候选人分低于阈值的 → popup log 显示"X: 分 45 < 60, 跳过"类信息
11. **检查项 6**: 同一候选人第二次遇到（或手动构造）→ popup log 显示"Y: 历史已打过招呼, 跳过"

- [ ] **Step 3: 手工 E2E — 项 7-8（异常路径）**

12. **检查项 7**: 在另一 tab `chrome://extensions` 里临时把 Boss DOM 里一个 script 注入 "操作过于频繁" 文字（DevTools console `document.body.innerText += "操作过于频繁"`）→ 下一轮循环应检测风控 halt
13. **检查项 8**: 临时把 cap 设为 1 → 打 1 人后第二轮应返 blocked_daily_cap halt

- [ ] **Step 4: 手工 E2E — 项 9（DB 落痕）**

14. **检查项 9**: SQL 直查：
```bash
cd D:/libz/AgenticHR && python -c "
from sqlalchemy import create_engine, text
e = create_engine('sqlite:///test.db')
with e.connect() as c:
    r = c.execute(text('SELECT id, name, boss_id, greet_status, source FROM resumes WHERE source=\"boss_zhipin\" AND greet_status=\"greeted\"')).fetchall()
    print(f'{len(r)} greeted resumes')
    for row in r: print(row)
    r2 = c.execute(text('SELECT f_stage, action, COUNT(*) FROM audit_events WHERE f_stage LIKE \"F3%\" GROUP BY f_stage, action')).fetchall()
    for row in r2: print(row)
"
```
验证：`greet_status='greeted'` 行数 == E2E 中 popup 显示的 greeted 计数；audit_events 有 `F3_evaluate`、`F3_greet_sent` 行。

- [ ] **Step 5: 写 CHANGELOG**

修改 `CHANGELOG.md`（若无则创建）— 顶部加：

```markdown
## [Unreleased] — 2026-04-XX

### Added (F3)
- 新增 `app/modules/recruit_bot/` 模块：Boss 推荐牛人页自动打招呼后端
- 4 个端点：`POST /api/recruit/evaluate_and_record`、`POST /api/recruit/record-greet`、`GET /api/recruit/daily-usage`、`PUT /api/recruit/daily-cap`
- Edge 扩展 popup 加 F3 section（岗位下拉 + 配额 + 开始按钮）
- content.js 加 `autoGreetRecommend()` 主循环 + 反检测工具（`simulateHumanClick` / `detectRiskControl`）
- 反检测硬约束：随机 2-5s 间隔、每 10 个长停 3-6s、事件序列、风控 DOM/文案扫描 halt、连续 3 次按钮无反应熔断

### Changed
- `users` 表加 `daily_cap`（默认 1000）
- `jobs` 表加 `greet_threshold`（默认 60）
- `resumes` 表加 `boss_id` / `greet_status` / `greeted_at`，加 `UNIQUE(user_id, boss_id)` 部分索引
- Alembic 迁移 `0010`

### Notes
- **禁止用招聘主账号跑 F3**，用 HR 小号（合规 R7）
- 话术非 LLM 生成，用 Boss 默认文案；无 HITL（见 spec §3）
- 模态抓详情留给 `F3_AI_PARSE_ENABLED=true` 未来打开（spec §5.2）
```

- [ ] **Step 6: 更新 memory**

修改 `C:/Users/neuro/.claude/projects/D--libz-AgenticHR/memory/project_f3_execution_state.md`：

name 改为 "F3 执行进度（完成，待用户验收后可开 F4）"，内容改为：

```markdown
---
name: F3 执行进度（完成，待用户验收）
description: F3 全部 T0-T10 任务完成，测试基线 ~394 passed，用户验收后可开 F4
type: project
---

**M3 F3 Boss 推荐牛人自动打招呼** — 全部 10 任务完成。

**最后 commit**：（填实际 hash）

**测试基线**：（填实际数字）passed / 7 pre-existing failed。F3 模块新增 21 测试。

**已知 Tech Debt（F4 前可选清）**：
1. content.js selectors 集 (`f3_selectors.js`) 只是占位 best guess，T1 的 DOM 精确化需在真实 Boss 页 DevTools 里验证并修正
2. `F3_AI_PARSE_ENABLED=true` 路径未实现，真要开还要写 modal 抓取 + LLM 解析 worker
3. 岗位对齐相似度算法 `stringSimilarity` 是朴素版，F4 若复用需换 Jaccard/Levenshtein

**Why**：M3 F3 全流程 TDD + Subagent-Driven 开发完成。

**How to apply**：
- 接 "继续 F4" 前必须先问用户 F3 是否手工 E2E 验收通过
- F4 brainstorm 从 `superpowers:brainstorming` 开始，不许跳步
```

- [ ] **Step 7: 最终回归 + commit**

```bash
python -m pytest tests/ -q --ignore=tests/e2e
git add CHANGELOG.md
git commit -m "docs(f3-T10): CHANGELOG + user manual E2E validation complete"
```

- [ ] **Step 8: 通知用户手工验收**

向用户报告：
- commit 列表
- 基线数字
- E2E 9 项 checklist 结果
- 要求用户手工验收后给绿灯

---

## 自我核查（Self-Review）

### 覆盖 check
- [ ] spec §3 决议表 Q1-Q9 → 全部在任务中实现（Q1 popup 下拉=T8；Q2 service 调 MatchingService=T3；Q3 job.greet_threshold=T0；Q4 无 HITL=不写；Q5 cap+节流=T4+T7；Q6 upsert+已greet skip+本次去重=T2+T3+T7；Q7 DOM 直抠不跑 AI=T6；Q8 相似度检查=T7；Q9 字段+UNIQUE=T0）
- [ ] spec §4 架构 → T0/T5/T7/T8 构成完整 A3 分层
- [ ] spec §5.1 schemas → T0 Step 3 全字段覆盖
- [ ] spec §5.2 LIST-only → T6 scrapeRecommendCard 实现
- [ ] spec §5.3 前端 → T8 三个函数 loadJobs/loadDailyUsage/startAutoRecruit/editCap
- [ ] spec §7 反检测 → T6/T7（simulateHumanClick 事件序列，detectRiskControl，节流 2-5s 与每 10 个 3-6s，连续 3 次无反应熔断）
- [ ] spec §8 迁移 → T0 Step 9
- [ ] spec §9 错误矩阵 14 项 → E1-E14 全在 T7 主循环 + T5 router 的 HTTP 错误映射中
- [ ] spec §10 测试策略 → T2-T5/T9 共 21 测试

### 占位扫
- [ ] 搜 "TBD" / "TODO" / "fill in" → 0（T1 有"T1 时精确化 selector"是实施注释，不是计划占位）
- [ ] 每 Step 代码块完整可执行 → 抽查 T3 Step 3、T7 Step 1 —— OK

### 类型一致性
- [ ] `ScrapedCandidate` 在 T0 定义，T2/T3/T6/T7 使用 —— 字段名一致
- [ ] `RecruitDecision.decision` 枚举在 T0 定义，T3/T7 全部引用同套字面量
- [ ] `greet_status` 枚举 `none/pending_greet/greeted/failed/skipped` 在 T0 加，T3/T4 更新时取值一致

### 任务依赖
- [ ] T1 独立（只改 extension 静态文件）
- [ ] T2-T5 可顺序（后端）
- [ ] T6 依赖 T1（用 F3_SELECTORS）
- [ ] T7 依赖 T6（用 scrapeRecommendCard/simulateHumanClick/detectRiskControl）
- [ ] T8 依赖 T7（通过 message 触发 autoGreetRecommend）
- [ ] T9 独立于前端（只调后端 service）
- [ ] T10 所有前置完成

---

**End of plan.**
