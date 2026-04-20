# F2: 简历解析 + 匹配打分 + 标签 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AgenticHR 加一条确定性 + 向量相似度的简历 × 岗位匹配通道：输入 `(resume, job)`，输出 5 维度分项得分 + 证据片段 + 预设标签 + 硬门槛判定，废弃旧 `ai_evaluation` LLM-only 打分路径。

**Architecture:**
- 新开 `app/modules/matching/` 模块：`scorers/` 下 5 个维度各一个纯函数 + `aggregator.py` 汇总 + `evidence.py` 生成证据；`service.py` 编排；`triggers.py` 接简历入库 / 能力模型发布的 BackgroundTasks。
- 新表 `matching_results` 存 `UNIQUE(resume_id, job_id)` 单对最新分数，`competency_hash` + `weights_hash` 支持过时检测。
- 前端 `Jobs.vue` 新增"匹配候选人" Tab，`Resumes.vue` 详情弹窗加"对接岗位分数"只读块。
- 旧 `/api/ai-evaluation/evaluate*` 返 410 Gone + `migrate_to` 字段；`/status` 保留给 F5 用。

**Tech Stack:** Python 3.11 · FastAPI · SQLAlchemy · Alembic · Pydantic v2 · pytest · bge-m3（通过 `core/llm` 和 `core/vector`）· Vue 3 + Element Plus。

**Design Reference:** [2026-04-20-f2-resume-matching-design.md](../specs/2026-04-20-f2-resume-matching-design.md)

---

## 前置约束（CLAUDE.md）

- **TDD 强制**：每个任务先写失败测试，再实现；不可跳过。
- **`core/` 不改**：本计划全部改动在 `modules/matching`、`modules/resume`、`modules/ai_evaluation`、`modules/screening` + 前端。如遇必须改 `core/` 的场景，**停下来问用户**。
- **基线维持**：F1 完工后 `pytest tests/` 通过数 N；F2 后需 ≥ N + 30。每个任务提交前跑全量。
- **文件头导入顺序**：标准库 → 第三方 → `app.*`，与现 codebase 一致。
- **中文文档字符串**：现模块大量使用中文 docstring，沿用风格。

---

## 文件结构规划

### 新建
```
app/modules/matching/
├── __init__.py
├── models.py                 # MatchingResult ORM
├── schemas.py                # Pydantic: MatchingResultResponse, EvidenceItem, ...
├── hashing.py                # competency_hash / weights_hash
├── router.py                 # /api/matching/* 路由
├── service.py                # MatchingService.score_pair / recompute
├── triggers.py               # T1/T2 触发逻辑
└── scorers/
    ├── __init__.py
    ├── skill.py
    ├── experience.py
    ├── seniority.py
    ├── education.py
    ├── industry.py
    ├── aggregator.py
    └── evidence.py

migrations/versions/0007_add_f2_matching.py

tests/modules/matching/
├── __init__.py
├── test_hashing.py
├── test_scorer_skill.py
├── test_scorer_experience.py
├── test_scorer_seniority.py
├── test_scorer_education.py
├── test_scorer_industry.py
├── test_aggregator.py
├── test_tags.py
├── test_evidence_deterministic.py
├── test_evidence_llm_fallback.py
├── test_service.py
├── test_router_score.py
├── test_router_results.py
├── test_router_recompute.py
└── test_deprecated_evaluate.py

tests/integration/
├── test_f2_trigger_resume_ingest.py
├── test_f2_trigger_competency_approve.py
├── test_f2_stale_detection.py
├── test_f2_upsert.py
├── test_f2_audit.py
└── test_f2_e2e_smoke.py
```

### 修改
```
app/modules/resume/models.py                  # + seniority 列
app/modules/resume/schemas.py                  # ResumeResponse + seniority
app/modules/resume/_ai_parse_worker.py         # 扩 LLM prompt 输出 seniority
app/modules/ai_evaluation/router.py            # /evaluate + /evaluate/batch → 410 Gone
app/modules/ai_evaluation/service.py           # 删除 evaluate_single / evaluate_batch
app/modules/ai_evaluation/schemas.py           # 删除 EvaluationRequest 等
app/modules/screening/router.py                # approve handler 末尾调 triggers.on_competency_approved
app/modules/resume/service.py                  # ai_parse 完成调 triggers.on_resume_parsed
app/main.py                                    # 注册 matching router
app/config.py                                  # 加 5 个 matching 配置
tests/conftest.py                              # 导入 matching.models 让 Base 注册
frontend/src/api.js                            # matchingApi 新增
frontend/src/views/Jobs.vue                    # 新增 "匹配候选人" Tab
frontend/src/views/Resumes.vue                 # 详情弹窗加 "对接岗位分数"
```

---

## Task 1: Alembic migration + Resume.seniority 列

**Files:**
- Create: `migrations/versions/0007_add_f2_matching.py`
- Modify: `app/modules/resume/models.py`
- Test: 手动跑 Alembic upgrade / downgrade

- [ ] **Step 1: 检查当前 migration head**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/alembic current`
Expected: 输出 `0006 (head)` 或类似

- [ ] **Step 2: 创建 migration 文件**

Create `migrations/versions/0007_add_f2_matching.py`:

```python
"""add f2 matching_results and resumes.seniority

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-20

"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'matching_results',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('resume_id', sa.Integer, nullable=False),
        sa.Column('job_id', sa.Integer, nullable=False),
        sa.Column('total_score', sa.Float, nullable=False),
        sa.Column('skill_score', sa.Float, nullable=False),
        sa.Column('experience_score', sa.Float, nullable=False),
        sa.Column('seniority_score', sa.Float, nullable=False),
        sa.Column('education_score', sa.Float, nullable=False),
        sa.Column('industry_score', sa.Float, nullable=False),
        sa.Column('hard_gate_passed', sa.Integer, nullable=False, server_default='1'),
        sa.Column('missing_must_haves', sa.Text, nullable=False, server_default='[]'),
        sa.Column('evidence', sa.Text, nullable=False, server_default='{}'),
        sa.Column('tags', sa.Text, nullable=False, server_default='[]'),
        sa.Column('competency_hash', sa.String(40), nullable=False),
        sa.Column('weights_hash', sa.String(40), nullable=False),
        sa.Column('scored_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('resume_id', 'job_id', name='uq_mr_resume_job'),
    )
    op.create_index('idx_mr_job_score', 'matching_results',
                    ['job_id', sa.text('total_score DESC')])
    op.create_index('idx_mr_resume', 'matching_results', ['resume_id'])

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.add_column(
            sa.Column('seniority', sa.String(20), nullable=False, server_default='')
        )


def downgrade() -> None:
    with op.batch_alter_table('resumes') as batch_op:
        batch_op.drop_column('seniority')

    op.drop_index('idx_mr_resume', 'matching_results')
    op.drop_index('idx_mr_job_score', 'matching_results')
    op.drop_table('matching_results')
```

- [ ] **Step 3: 在 Resume ORM 加 seniority 列**

Modify `app/modules/resume/models.py` — 在 `reject_reason` 列之后加：

```python
    seniority = Column(String(20), default="", nullable=False)
```

- [ ] **Step 4: 跑 upgrade 并验证**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade 0006 -> 0007, add f2 matching_results and resumes.seniority`

Run: `cd D:/libz/AgenticHR && .venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('data/hr.db'); print([r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')])"`
Expected: 输出列表包含 `matching_results`

- [ ] **Step 5: 跑 downgrade 验证可逆**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/alembic downgrade -1 && .venv/Scripts/alembic upgrade head`
Expected: 两条命令都成功，无报错

- [ ] **Step 6: Commit**

```bash
cd D:/libz/AgenticHR
git add migrations/versions/0007_add_f2_matching.py app/modules/resume/models.py
git commit -m "feat(f2): alembic migration for matching_results + resumes.seniority"
```

---

## Task 2: MatchingResult ORM + 模块脚手架

**Files:**
- Create: `app/modules/matching/__init__.py`
- Create: `app/modules/matching/models.py`
- Create: `app/modules/matching/scorers/__init__.py`
- Create: `tests/modules/matching/__init__.py`
- Modify: `tests/conftest.py` — 导入 matching.models
- Test: 手动建表

- [ ] **Step 1: 创建包结构**

Create empty files:
- `app/modules/matching/__init__.py`（空文件）
- `app/modules/matching/scorers/__init__.py`（空文件）
- `tests/modules/matching/__init__.py`（空文件）

- [ ] **Step 2: 写 MatchingResult ORM**

Create `app/modules/matching/models.py`:

```python
"""F2 匹配结果 ORM."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint

from app.database import Base


class MatchingResult(Base):
    __tablename__ = "matching_results"
    __table_args__ = (
        UniqueConstraint("resume_id", "job_id", name="uq_mr_resume_job"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    resume_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, nullable=False)

    total_score = Column(Float, nullable=False)
    skill_score = Column(Float, nullable=False)
    experience_score = Column(Float, nullable=False)
    seniority_score = Column(Float, nullable=False)
    education_score = Column(Float, nullable=False)
    industry_score = Column(Float, nullable=False)

    hard_gate_passed = Column(Integer, nullable=False, default=1)
    missing_must_haves = Column(Text, nullable=False, default="[]")
    evidence = Column(Text, nullable=False, default="{}")
    tags = Column(Text, nullable=False, default="[]")

    competency_hash = Column(String(40), nullable=False)
    weights_hash = Column(String(40), nullable=False)

    scored_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
```

- [ ] **Step 3: 让 conftest 注册 matching.models**

Modify `tests/conftest.py` — 在现有 `import app.modules.notification.models` 后加一行：

```python
import app.modules.matching.models  # noqa: F401
```

- [ ] **Step 4: 跑一遍现有测试确认零回归**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/ -x --tb=short -q`
Expected: 全部 pass，通过数 ≥ F1 基线

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/ tests/modules/matching/ tests/conftest.py
git commit -m "feat(f2): add MatchingResult ORM + package scaffolding"
```

---

## Task 3: Hashing 工具（competency_hash + weights_hash）

**Files:**
- Create: `app/modules/matching/hashing.py`
- Test: `tests/modules/matching/test_hashing.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_hashing.py`:

```python
"""Hashing utilities for staleness detection."""
from app.modules.matching.hashing import compute_competency_hash, compute_weights_hash


def test_same_content_same_hash():
    c1 = {"hard_skills": [{"name": "Python", "weight": 8}], "job_level": "senior"}
    c2 = {"job_level": "senior", "hard_skills": [{"name": "Python", "weight": 8}]}
    assert compute_competency_hash(c1) == compute_competency_hash(c2)


def test_content_change_hash_change():
    c1 = {"hard_skills": [{"name": "Python"}]}
    c2 = {"hard_skills": [{"name": "Java"}]}
    assert compute_competency_hash(c1) != compute_competency_hash(c2)


def test_empty_is_stable():
    assert compute_competency_hash({}) == compute_competency_hash({})


def test_weights_hash_shape():
    w = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}
    h = compute_weights_hash(w)
    assert len(h) == 40   # SHA1 hex
    assert compute_weights_hash(w) == compute_weights_hash(w)


def test_weights_change_hash_change():
    w1 = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}
    w2 = {"skill_match": 40, "experience": 25, "seniority": 15, "education": 10, "industry": 10}
    assert compute_weights_hash(w1) != compute_weights_hash(w2)
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_hashing.py -v`
Expected: `ImportError: cannot import name 'compute_competency_hash'`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/hashing.py`:

```python
"""能力模型 + 评分权重的 SHA1 哈希, 用于 matching_result 过时检测."""
import hashlib
import json
from typing import Any


def _canonical_sha1(payload: Any) -> str:
    """dict/list 按 sorted keys 规整化后算 SHA1 hex."""
    if payload is None:
        return ""
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def compute_competency_hash(competency_model: dict) -> str:
    """岗位能力模型 (dict, 通常来自 jobs.competency_model JSON 列) → SHA1 hex."""
    return _canonical_sha1(competency_model or {})


def compute_weights_hash(weights: dict) -> str:
    """评分权重 (dict, 通常来自 ScoringWeights.model_dump()) → SHA1 hex."""
    return _canonical_sha1(weights or {})
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_hashing.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/hashing.py tests/modules/matching/test_hashing.py
git commit -m "feat(f2): competency_hash + weights_hash SHA1 utilities"
```

---

## Task 4: 技能匹配 scorer（两段式：canonical_id + 向量相似度）

**Files:**
- Create: `app/modules/matching/scorers/skill.py`
- Test: `tests/modules/matching/test_scorer_skill.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_scorer_skill.py`:

```python
"""Skill matching scorer."""
from unittest.mock import patch
from app.modules.matching.scorers.skill import score_skill


def _hs(name, weight=5, must_have=False, canonical_id=None, level="熟练"):
    return {"name": name, "weight": weight, "must_have": must_have,
            "canonical_id": canonical_id, "level": level}


def test_empty_hard_skills_full_score():
    score, missing = score_skill([], "Python, Go")
    assert score == 100.0
    assert missing == []


def test_canonical_id_exact_match():
    hs = [_hs("Python", canonical_id=1)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals") as m:
        m.return_value = {1}
        score, missing = score_skill(hs, "Python")
    assert score == 100.0
    assert missing == []


def test_vector_above_075_full_coverage():
    hs = [_hs("Python 开发", canonical_id=None)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.88):
        score, missing = score_skill(hs, "Python")
    assert 85 < score <= 100   # 0.88 乘以权重占比


def test_vector_edge_060_to_075_discounted():
    hs = [_hs("DevOps", canonical_id=None)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.65):
        score, missing = score_skill(hs, "Linux")
    # 0.65 * 0.5 = 0.325 coverage → ~32.5 分
    assert 30 < score < 35


def test_below_060_zero_coverage():
    hs = [_hs("Kubernetes", canonical_id=None)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.40):
        score, missing = score_skill(hs, "Docker")
    assert score == 0.0
    assert missing == []   # must_have=False 不记录 missing


def test_missing_must_have_recorded():
    hs = [_hs("Python", canonical_id=None, must_have=True)]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value=set()), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.30):
        score, missing = score_skill(hs, "Java")
    assert score == 0.0
    assert missing == ["Python"]


def test_weighted_aggregation():
    hs = [
        _hs("Python", weight=10, canonical_id=1),   # 匹配 → coverage=1, 权重 10
        _hs("Java", weight=2, canonical_id=2),      # 不匹配 → coverage=0, 权重 2
    ]
    with patch("app.modules.matching.scorers.skill._lookup_resume_canonicals", return_value={1}), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.0):
        score, _ = score_skill(hs, "Python")
    # (10 * 1.0 + 2 * 0.0) / (10 + 2) * 100 = 83.33
    assert 83 < score < 84
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_skill.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/scorers/skill.py`:

```python
"""技能匹配 scorer — canonical_id 精确匹配 + bge-m3 向量相似度两段式."""
import logging
from typing import Any

from app.config import settings
from app.core.vector.service import cosine_similarity, unpack_vector

logger = logging.getLogger(__name__)

_EXACT_THRESHOLD = getattr(settings, "matching_skill_sim_exact", 0.75)
_EDGE_THRESHOLD = getattr(settings, "matching_skill_sim_edge", 0.60)


def _parse_resume_skills(resume_skills_text: str) -> list[str]:
    """'Python, Go, FastAPI' → ['Python', 'Go', 'FastAPI'], 去空"""
    if not resume_skills_text:
        return []
    return [s.strip() for s in resume_skills_text.split(",") if s.strip()]


def _lookup_resume_canonicals(resume_skill_names: list[str], db_session=None) -> set[int]:
    """简历侧技能名 → 技能库 canonical_id 集合. db_session=None 时返回空集合（测试用）."""
    if not db_session or not resume_skill_names:
        return set()
    from sqlalchemy import text
    placeholders = ",".join(":n" + str(i) for i in range(len(resume_skill_names)))
    params = {f"n{i}": n for i, n in enumerate(resume_skill_names)}
    query = text(f"SELECT DISTINCT canonical_id FROM skills WHERE name IN ({placeholders}) AND canonical_id IS NOT NULL")
    try:
        rows = db_session.execute(query, params).fetchall()
        return {r[0] for r in rows if r[0] is not None}
    except Exception as e:
        logger.warning(f"lookup canonicals failed: {e}")
        return set()


def _max_vector_similarity(skill_name: str, resume_skill_names: list[str], db_session=None) -> float:
    """技能名对所有简历侧技能名的最大 cosine. 默认走 skills 表 embedding 列."""
    if not resume_skill_names or not db_session:
        return 0.0
    from sqlalchemy import text
    try:
        row = db_session.execute(
            text("SELECT embedding FROM skills WHERE name = :n LIMIT 1"),
            {"n": skill_name},
        ).fetchone()
        if not row or not row[0]:
            return 0.0
        hs_vec = unpack_vector(row[0])

        best = 0.0
        for rn in resume_skill_names:
            r = db_session.execute(
                text("SELECT embedding FROM skills WHERE name = :n LIMIT 1"),
                {"n": rn},
            ).fetchone()
            if r and r[0]:
                sim = cosine_similarity(hs_vec, unpack_vector(r[0]))
                if sim > best:
                    best = sim
        return best
    except Exception as e:
        logger.warning(f"vector similarity failed for {skill_name}: {e}")
        return 0.0


def score_skill(
    hard_skills: list[dict],
    resume_skills_text: str,
    db_session: Any = None,
) -> tuple[float, list[str]]:
    """返回 (skill_score 0-100, missing_must_haves: list[str]).

    hard_skills: list of dicts from competency_model['hard_skills'], 每个含
                 name/weight/must_have/canonical_id/level.
    resume_skills_text: Resume.skills 列（逗号分隔字符串）.
    db_session: 供 skills 表 canonical_id 和 embedding 查询；None 时降级到纯名字匹配.
    """
    if not hard_skills:
        return 100.0, []

    resume_skill_names = _parse_resume_skills(resume_skills_text)
    resume_canonicals = _lookup_resume_canonicals(resume_skill_names, db_session)

    total_weight = 0
    weighted_coverage = 0.0
    missing_must_haves: list[str] = []

    for hs in hard_skills:
        weight = int(hs.get("weight", 5))
        total_weight += weight

        coverage = 0.0
        cid = hs.get("canonical_id")
        if cid is not None and cid in resume_canonicals:
            coverage = 1.0
        else:
            sim = _max_vector_similarity(hs["name"], resume_skill_names, db_session)
            if sim >= _EXACT_THRESHOLD:
                coverage = sim
            elif sim >= _EDGE_THRESHOLD:
                coverage = sim * 0.5
            else:
                coverage = 0.0
                if hs.get("must_have"):
                    missing_must_haves.append(hs["name"])

        weighted_coverage += weight * coverage

    if total_weight == 0:
        return 100.0, missing_must_haves

    return round(weighted_coverage / total_weight * 100.0, 2), missing_must_haves
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_skill.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/skill.py tests/modules/matching/test_scorer_skill.py
git commit -m "feat(f2): skill matching scorer (canonical_id + vector similarity)"
```

---

## Task 5: 工作经验 scorer

**Files:**
- Create: `app/modules/matching/scorers/experience.py`
- Test: `tests/modules/matching/test_scorer_experience.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_scorer_experience.py`:

```python
from app.modules.matching.scorers.experience import score_experience


def test_in_range():
    assert score_experience(5, {"years_min": 3, "years_max": 8}) == 100.0


def test_at_lower_bound():
    assert score_experience(3, {"years_min": 3, "years_max": 8}) == 100.0


def test_at_upper_bound():
    assert score_experience(8, {"years_min": 3, "years_max": 8}) == 100.0


def test_under_qualified_linear():
    score = score_experience(2, {"years_min": 4, "years_max": 8})
    assert score == 50.0   # 2/4 * 100


def test_under_qualified_ymin_zero():
    assert score_experience(0, {"years_min": 0, "years_max": 5}) == 100.0


def test_over_qualified_linear():
    score = score_experience(10, {"years_min": 3, "years_max": 5})
    # 过度 5 年 → 100 - 50 = 50, 但最低保 60
    assert score == 60.0


def test_slightly_over_above_60_floor():
    score = score_experience(7, {"years_min": 3, "years_max": 5})
    assert score == 80.0   # 100 - (7-5)*10


def test_ymax_none_defaults_ymin_plus_10():
    score = score_experience(12, {"years_min": 3, "years_max": None})
    # ymax = 13, years 12 在范围内
    assert score == 100.0


def test_over_ymax_none_default():
    score = score_experience(20, {"years_min": 3, "years_max": None})
    # ymax = 13, 过度 7 → 30, 底 60
    assert score == 60.0
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_experience.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/scorers/experience.py`:

```python
"""工作经验 scorer — 数值比较."""


def score_experience(resume_work_years: int, experience_requirement: dict) -> float:
    """返回 0-100 分.

    experience_requirement: competency_model['experience'] dict with
        years_min (int), years_max (int | None).
    """
    years = max(0, int(resume_work_years or 0))
    ymin = int(experience_requirement.get("years_min", 0) or 0)
    ymax_raw = experience_requirement.get("years_max")
    ymax = int(ymax_raw) if ymax_raw is not None else (ymin + 10)

    if ymin <= years <= ymax:
        return 100.0
    if years < ymin:
        if ymin == 0:
            return 100.0
        return round(years / ymin * 100.0, 2)
    # years > ymax
    return max(60.0, 100.0 - (years - ymax) * 10)
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_experience.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/experience.py tests/modules/matching/test_scorer_experience.py
git commit -m "feat(f2): experience scorer (years range with over/under decay)"
```

---

## Task 6: 职级 scorer（LEVEL_MAP 关键词 + ordinal）

**Files:**
- Create: `app/modules/matching/scorers/seniority.py`
- Test: `tests/modules/matching/test_scorer_seniority.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_scorer_seniority.py`:

```python
from app.modules.matching.scorers.seniority import score_seniority, match_ordinal


def test_match_ordinal_junior():
    assert match_ordinal("初级工程师") == 1
    assert match_ordinal("junior") == 1


def test_match_ordinal_senior():
    assert match_ordinal("高级工程师") == 3
    assert match_ordinal("Senior Engineer") == 3


def test_match_ordinal_lead():
    assert match_ordinal("技术总监") == 4
    assert match_ordinal("Lead") == 4
    assert match_ordinal("Principal") == 4


def test_match_ordinal_default_mid():
    assert match_ordinal("") == 2
    assert match_ordinal("未知岗位") == 2


def test_equal_level():
    assert score_seniority("高级", "Senior 后端工程师") == 100.0


def test_candidate_higher():
    assert score_seniority("专家", "中级") == 100.0


def test_candidate_one_below():
    assert score_seniority("中级", "高级后端") == 60.0


def test_candidate_two_below():
    assert score_seniority("初级", "专家") == 20.0


def test_empty_seniority_defaults_mid():
    # Resume 未推断时默认中级 (ordinal=2)
    assert score_seniority("", "中级") == 100.0
    assert score_seniority("", "高级") == 60.0
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_seniority.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/scorers/seniority.py`:

```python
"""职级 scorer — free-text 关键词映射到 1-4 ordinal, 对比打分."""

# 关键词 → ordinal, 顺序从高到低匹配（避免"高级"被"初级"误伤）
_LEVEL_PATTERNS = [
    (("专家", "lead", "主管", "总监", "staff", "principal"), 4),
    (("高级", "senior"), 3),
    (("中级", "mid", "regular"), 2),
    (("初级", "junior", "实习"), 1),
]


def match_ordinal(text: str) -> int:
    """任意职级描述 → 1-4 ordinal. 命中不到时默认 2（中级）."""
    t = (text or "").lower()
    for keywords, ord_ in _LEVEL_PATTERNS:
        if any(k.lower() in t for k in keywords):
            return ord_
    return 2


def score_seniority(resume_seniority: str, competency_job_level: str) -> float:
    """返回 0-100 分.

    resume_seniority: Resume.seniority ('初级'/'中级'/'高级'/'专家'/'').
    competency_job_level: competency_model['job_level'] free text.
    """
    required = match_ordinal(competency_job_level)
    candidate = match_ordinal(resume_seniority)

    diff = candidate - required
    if diff >= 0:
        return 100.0
    if diff == -1:
        return 60.0
    return 20.0
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_seniority.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/seniority.py tests/modules/matching/test_scorer_seniority.py
git commit -m "feat(f2): seniority scorer (keyword-to-ordinal matching)"
```

---

## Task 7: 学历 scorer

**Files:**
- Create: `app/modules/matching/scorers/education.py`
- Test: `tests/modules/matching/test_scorer_education.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_scorer_education.py`:

```python
from app.modules.matching.scorers.education import score_education


def test_exact_match():
    assert score_education("本科", {"min_level": "本科"}) == 100.0


def test_over_qualified():
    assert score_education("硕士", {"min_level": "本科"}) == 100.0


def test_one_level_below():
    assert score_education("大专", {"min_level": "本科"}) == 60.0


def test_two_levels_below():
    assert score_education("大专", {"min_level": "硕士"}) == 20.0


def test_three_levels_below():
    # resume 未知学历 (ord=0) 对 min_level 博士 (ord=4) → max(0, 100-4*40) = 0
    assert score_education("", {"min_level": "博士"}) == 0.0


def test_empty_resume_edu():
    # 未知简历学历 (ord=0), min_level 本科 (ord=2) → max(0, 100-80) = 20
    assert score_education("", {"min_level": "本科"}) == 20.0


def test_default_min_level_bachelor():
    assert score_education("硕士", {}) == 100.0   # 默认 min_level=本科
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_education.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/scorers/education.py`:

```python
"""学历 scorer — 大专/本科/硕士/博士 ordinal 比较."""

_EDU_ORD = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


def score_education(resume_education: str, education_requirement: dict) -> float:
    """返回 0-100 分."""
    r = _EDU_ORD.get((resume_education or "").strip(), 0)
    m = _EDU_ORD.get((education_requirement.get("min_level") or "本科").strip(), 2)

    if r >= m:
        return 100.0
    return max(0.0, 100.0 - (m - r) * 40)
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_education.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/education.py tests/modules/matching/test_scorer_education.py
git commit -m "feat(f2): education scorer (ordinal level comparison)"
```

---

## Task 8: 行业 scorer

**Files:**
- Create: `app/modules/matching/scorers/industry.py`
- Test: `tests/modules/matching/test_scorer_industry.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_scorer_industry.py`:

```python
from unittest.mock import patch
from app.modules.matching.scorers.industry import score_industry


def test_empty_industries_full_score():
    assert score_industry("任意工作经历", []) == 100.0


def test_keyword_full_hit():
    assert score_industry("曾在某互联网公司任职 5 年", ["互联网"]) == 100.0


def test_keyword_case_insensitive():
    assert score_industry("worked at a FinTech firm", ["fintech"]) == 100.0


def test_partial_hit():
    # 2 行业要求, 命中 1 个
    score = score_industry("在互联网公司任职", ["互联网", "教育"])
    assert score == 50.0


def test_no_hit_no_vector_fallback():
    with patch("app.modules.matching.scorers.industry._vector_match", return_value=False):
        score = score_industry("在汽车工厂工作", ["金融"])
    assert score == 0.0


def test_vector_fallback_hit():
    with patch("app.modules.matching.scorers.industry._vector_match", return_value=True):
        # 关键词未命中，向量命中 → 算 1 hit
        score = score_industry("曾在教培机构", ["教育"])
    assert score == 100.0


def test_empty_work_experience():
    assert score_industry("", ["互联网"]) == 0.0
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_industry.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/scorers/industry.py`:

```python
"""行业 scorer — 关键词包含 + 向量相似度 fallback."""
import logging
from typing import Any

from app.config import settings
from app.core.vector.service import cosine_similarity

logger = logging.getLogger(__name__)

_SIM_THRESHOLD = getattr(settings, "matching_industry_sim", 0.70)


def _vector_match(industry: str, work_experience: str, db_session: Any = None) -> bool:
    """行业名 vs 工作经历文本前 500 字的 bge-m3 相似度 >= 阈值. db_session=None → False."""
    if not db_session or not industry or not work_experience:
        return False
    try:
        from sqlalchemy import text
        row_ind = db_session.execute(
            text("SELECT embedding FROM skills WHERE name = :n LIMIT 1"),
            {"n": industry},
        ).fetchone()
        if not row_ind or not row_ind[0]:
            return False
        # V1: work_experience 没有预存 embedding, 实时 embed 需调 LLM API；
        # 留 hook 在此函数签名里，V2 再接通 core/llm embedding 服务。暂时不命中。
        return False
    except Exception as e:
        logger.warning(f"industry vector match failed: {e}")
        return False


def score_industry(
    resume_work_experience: str,
    industries: list[str],
    db_session: Any = None,
) -> float:
    """返回 0-100 分."""
    if not industries:
        return 100.0
    if not resume_work_experience:
        return 0.0

    work_lower = resume_work_experience.lower()
    hits = 0
    for industry in industries:
        if not industry:
            continue
        if industry.lower() in work_lower:
            hits += 1
        elif _vector_match(industry, resume_work_experience, db_session):
            hits += 1

    return round(hits / len(industries) * 100.0, 2)
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_scorer_industry.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/industry.py tests/modules/matching/test_scorer_industry.py
git commit -m "feat(f2): industry scorer (keyword + vector fallback)"
```

---

## Task 9: 聚合器（加权求和 + 硬门槛 + 标签派生）

**Files:**
- Create: `app/modules/matching/scorers/aggregator.py`
- Test: `tests/modules/matching/test_aggregator.py`
- Test: `tests/modules/matching/test_tags.py`

- [ ] **Step 1: 写 aggregator 失败测试**

Create `tests/modules/matching/test_aggregator.py`:

```python
from app.modules.matching.scorers.aggregator import aggregate


_WEIGHTS = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}


def test_weighted_sum_no_hard_gate():
    result = aggregate(
        dim_scores={"skill": 80, "experience": 60, "seniority": 70, "education": 100, "industry": 50},
        missing_must_haves=[],
        weights=_WEIGHTS,
    )
    # 80*0.35 + 60*0.30 + 70*0.15 + 100*0.10 + 50*0.10 = 28+18+10.5+10+5 = 71.5
    assert result["total_score"] == 71.5
    assert result["hard_gate_passed"] is True


def test_hard_gate_caps_at_29():
    result = aggregate(
        dim_scores={"skill": 90, "experience": 90, "seniority": 90, "education": 90, "industry": 90},
        missing_must_haves=["Python"],
        weights=_WEIGHTS,
    )
    # raw = 90, * 0.4 = 36, min with 29 → 29
    assert result["total_score"] == 29.0
    assert result["hard_gate_passed"] is False


def test_hard_gate_below_29_preserves():
    # raw 很低时 * 0.4 小于 29, 保留该值
    result = aggregate(
        dim_scores={"skill": 30, "experience": 30, "seniority": 30, "education": 30, "industry": 30},
        missing_must_haves=["Python"],
        weights=_WEIGHTS,
    )
    # raw = 30, * 0.4 = 12, min(12, 29) = 12
    assert result["total_score"] == 12.0


def test_all_dims_present():
    result = aggregate(
        dim_scores={"skill": 100, "experience": 100, "seniority": 100, "education": 100, "industry": 100},
        missing_must_haves=[],
        weights=_WEIGHTS,
    )
    assert result["total_score"] == 100.0


def test_zero_score():
    result = aggregate(
        dim_scores={"skill": 0, "experience": 0, "seniority": 0, "education": 0, "industry": 0},
        missing_must_haves=[],
        weights=_WEIGHTS,
    )
    assert result["total_score"] == 0.0
```

- [ ] **Step 2: 写 tags 失败测试**

Create `tests/modules/matching/test_tags.py`:

```python
from app.modules.matching.scorers.aggregator import derive_tags


def test_high_match_80():
    tags = derive_tags(total_score=80, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "高匹配" in tags


def test_mid_match_79():
    tags = derive_tags(total_score=79, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "中匹配" in tags
    assert "高匹配" not in tags


def test_low_match_40():
    tags = derive_tags(total_score=40, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "低匹配" in tags


def test_no_match_below_40():
    tags = derive_tags(total_score=39, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=100)
    assert "不匹配" in tags


def test_hard_gate_fail_takes_priority():
    tags = derive_tags(total_score=29, hard_gate_passed=False,
                       missing=["Python"], education_score=100, experience_score=100)
    assert "硬门槛未过" in tags
    assert "必须项缺失-Python" in tags
    # 硬门槛未过时不应该有匹配等级 tag
    assert "不匹配" not in tags
    assert "高匹配" not in tags


def test_missing_must_haves_truncated_to_3():
    tags = derive_tags(
        total_score=29, hard_gate_passed=False,
        missing=["Python", "Go", "Rust", "K8s", "Docker"],
        education_score=100, experience_score=100,
    )
    missing_tags = [t for t in tags if t.startswith("必须项缺失-")]
    assert len(missing_tags) == 3


def test_education_low_adds_tag():
    tags = derive_tags(total_score=70, hard_gate_passed=True, missing=[],
                       education_score=40, experience_score=100)
    assert "学历不达标" in tags


def test_experience_low_adds_tag():
    tags = derive_tags(total_score=70, hard_gate_passed=True, missing=[],
                       education_score=100, experience_score=40)
    assert "经验不足" in tags
```

- [ ] **Step 3: 验证两个测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_aggregator.py tests/modules/matching/test_tags.py -v`
Expected: `ImportError`

- [ ] **Step 4: 写实现**

Create `app/modules/matching/scorers/aggregator.py`:

```python
"""聚合分项得分 + 硬门槛 + 标签派生."""


def aggregate(
    dim_scores: dict,
    missing_must_haves: list[str],
    weights: dict,
) -> dict:
    """返回 {total_score, hard_gate_passed}.

    dim_scores keys: skill/experience/seniority/education/industry.
    weights keys: skill_match/experience/seniority/education/industry. Sum 必须 = 100.
    """
    raw = (
        dim_scores["skill"]      * weights["skill_match"] +
        dim_scores["experience"] * weights["experience"] +
        dim_scores["seniority"]  * weights["seniority"] +
        dim_scores["education"]  * weights["education"] +
        dim_scores["industry"]   * weights["industry"]
    ) / 100.0

    if missing_must_haves:
        total = min(raw * 0.4, 29.0)
        hard_gate_passed = False
    else:
        total = raw
        hard_gate_passed = True

    return {
        "total_score": round(total, 2),
        "hard_gate_passed": hard_gate_passed,
    }


def derive_tags(
    total_score: float,
    hard_gate_passed: bool,
    missing: list[str],
    education_score: float,
    experience_score: float,
) -> list[str]:
    """从分数 + 硬门槛结果派生预设结构化标签."""
    tags: list[str] = []
    if not hard_gate_passed:
        tags.append("硬门槛未过")
        for skill in missing[:3]:
            tags.append(f"必须项缺失-{skill}")
    else:
        if total_score >= 80:
            tags.append("高匹配")
        elif total_score >= 60:
            tags.append("中匹配")
        elif total_score >= 40:
            tags.append("低匹配")
        else:
            tags.append("不匹配")

    if education_score < 50:
        tags.append("学历不达标")
    if experience_score < 50:
        tags.append("经验不足")

    return tags
```

- [ ] **Step 5: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_aggregator.py tests/modules/matching/test_tags.py -v`
Expected: 13 passed

- [ ] **Step 6: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/aggregator.py tests/modules/matching/test_aggregator.py tests/modules/matching/test_tags.py
git commit -m "feat(f2): aggregator (weighted sum + hard gate) + tag derivation"
```

---

## Task 10: Deterministic 证据生成

**Files:**
- Create: `app/modules/matching/scorers/evidence.py`
- Test: `tests/modules/matching/test_evidence_deterministic.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_evidence_deterministic.py`:

```python
from app.modules.matching.scorers.evidence import build_deterministic_evidence


class _FakeResume:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_skill_offset_in_skills_field():
    resume = _FakeResume(
        skills="Python, Go, FastAPI",
        work_experience="", project_experience="", work_years=3, education="本科",
    )
    ev = build_deterministic_evidence(
        resume=resume,
        matched_skills=["Python"],
        experience_range=(3, 8),
        matched_industries=[],
    )
    skill_ev = ev["skill"]
    assert len(skill_ev) == 1
    assert skill_ev[0]["source"] == "skills"
    assert skill_ev[0]["text"] == "匹配到 Python"
    start, end = skill_ev[0]["offset"]
    assert resume.skills[start:end].lower() == "python"


def test_skill_falls_back_to_project_experience():
    resume = _FakeResume(
        skills="",
        work_experience="",
        project_experience="用 FastAPI 做过三个后端项目",
        work_years=3, education="本科",
    )
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=["FastAPI"],
        experience_range=(3, 8), matched_industries=[],
    )
    assert ev["skill"][0]["source"] == "project_experience"


def test_experience_evidence_no_offset():
    resume = _FakeResume(skills="", work_experience="", project_experience="",
                         work_years=5, education="本科")
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[], experience_range=(3, 8),
        matched_industries=[],
    )
    assert ev["experience"][0]["source"] == "work_years"
    assert ev["experience"][0]["offset"] is None
    assert "5" in ev["experience"][0]["text"]


def test_industry_keyword_offset():
    resume = _FakeResume(
        skills="", work_experience="曾在某互联网公司任职 5 年",
        project_experience="", work_years=5, education="本科",
    )
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[],
        experience_range=(3, 8), matched_industries=["互联网"],
    )
    assert ev["industry"][0]["source"] == "work_experience"
    start, end = ev["industry"][0]["offset"]
    assert resume.work_experience[start:end] == "互联网"


def test_unmatched_skill_not_in_evidence():
    resume = _FakeResume(skills="Python", work_experience="",
                         project_experience="", work_years=3, education="本科")
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[],
        experience_range=(3, 8), matched_industries=[],
    )
    assert ev["skill"] == []


def test_education_evidence():
    resume = _FakeResume(skills="", work_experience="", project_experience="",
                         work_years=3, education="硕士")
    ev = build_deterministic_evidence(
        resume=resume, matched_skills=[],
        experience_range=(3, 8), matched_industries=[],
    )
    assert ev["education"][0]["source"] == "education"
    assert "硕士" in ev["education"][0]["text"]
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_evidence_deterministic.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/scorers/evidence.py`:

```python
"""证据片段生成 — deterministic 定位 + 可选 LLM 文案增强."""
import re
from typing import Any


def _find_offset(pattern: str, text: str) -> tuple[int, int] | None:
    """忽略大小写找首次出现的 (start, end). 找不到返回 None."""
    if not pattern or not text:
        return None
    m = re.search(re.escape(pattern), text, re.IGNORECASE)
    if m:
        return [m.start(), m.end()]
    return None


_SKILL_SOURCES = ["skills", "project_experience", "work_experience", "self_evaluation"]


def _locate_skill(resume: Any, skill: str) -> dict:
    """在简历多个字段里找 skill 首次出现. 找不到返回 offset=None + source='' + 模板文本."""
    for src in _SKILL_SOURCES:
        text = getattr(resume, src, "") or ""
        off = _find_offset(skill, text)
        if off is not None:
            return {"text": f"匹配到 {skill}", "source": src, "offset": off}
    return {"text": f"匹配到 {skill}（简历原文未精确定位）", "source": "", "offset": None}


def build_deterministic_evidence(
    resume: Any,
    matched_skills: list[str],
    experience_range: tuple[int, int],
    matched_industries: list[str],
) -> dict:
    """返回按维度分组的 evidence dict."""
    evidence: dict = {"skill": [], "experience": [], "seniority": [], "education": [], "industry": []}

    for skill in matched_skills:
        evidence["skill"].append(_locate_skill(resume, skill))

    ymin, ymax = experience_range
    years = getattr(resume, "work_years", 0) or 0
    evidence["experience"].append({
        "text": f"工作年限 {years} 年，要求 {ymin}-{ymax} 年",
        "source": "work_years",
        "offset": None,
    })

    seniority = getattr(resume, "seniority", "") or ""
    if seniority:
        evidence["seniority"].append({
            "text": f"职级推断：{seniority}",
            "source": "seniority",
            "offset": None,
        })

    education = getattr(resume, "education", "") or ""
    if education:
        evidence["education"].append({
            "text": f"学历：{education}",
            "source": "education",
            "offset": None,
        })

    for industry in matched_industries:
        work_exp = getattr(resume, "work_experience", "") or ""
        off = _find_offset(industry, work_exp)
        if off is not None:
            evidence["industry"].append({
                "text": f"行业匹配：{industry}",
                "source": "work_experience",
                "offset": off,
            })
        else:
            evidence["industry"].append({
                "text": f"行业匹配：{industry}（未精确定位）",
                "source": "",
                "offset": None,
            })

    return evidence
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_evidence_deterministic.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/evidence.py tests/modules/matching/test_evidence_deterministic.py
git commit -m "feat(f2): deterministic evidence generator with offset locating"
```

---

## Task 11: LLM 证据增强 + 失败降级

**Files:**
- Modify: `app/modules/matching/scorers/evidence.py`
- Test: `tests/modules/matching/test_evidence_llm_fallback.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_evidence_llm_fallback.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.scorers.evidence import enhance_evidence_with_llm
from app.core.llm.provider import LLMError


class _FakeResume:
    name = "张三"
    skills = "Python, Go"


@pytest.mark.asyncio
async def test_llm_success_overwrites_text():
    base_evidence = {
        "skill": [{"text": "匹配到 Python", "source": "skills", "offset": [0, 6]}],
        "experience": [{"text": "工作年限 5 年", "source": "work_years", "offset": None}],
        "seniority": [], "education": [], "industry": [],
    }
    llm_output = {
        "skill": ["Python 技能满分匹配"],
        "experience": ["5 年经验贴合要求"],
        "seniority": [], "education": [], "industry": [],
    }
    with patch("app.modules.matching.scorers.evidence._call_llm",
               new=AsyncMock(return_value=llm_output)):
        result = await enhance_evidence_with_llm(base_evidence, _FakeResume(), dim_scores={})

    # text 被覆盖, source/offset 保留
    assert result["skill"][0]["text"] == "Python 技能满分匹配"
    assert result["skill"][0]["source"] == "skills"
    assert result["skill"][0]["offset"] == [0, 6]
    assert result["experience"][0]["text"] == "5 年经验贴合要求"


@pytest.mark.asyncio
async def test_llm_failure_preserves_deterministic():
    base_evidence = {
        "skill": [{"text": "匹配到 Python", "source": "skills", "offset": [0, 6]}],
        "experience": [], "seniority": [], "education": [], "industry": [],
    }
    with patch("app.modules.matching.scorers.evidence._call_llm",
               new=AsyncMock(side_effect=LLMError("API down"))):
        result = await enhance_evidence_with_llm(base_evidence, _FakeResume(), dim_scores={})

    assert result["skill"][0]["text"] == "匹配到 Python"
    assert result["skill"][0]["offset"] == [0, 6]


@pytest.mark.asyncio
async def test_llm_shorter_output_extras_preserved():
    # LLM 只返回 1 条但 base 有 2 条 → 第一条覆盖, 第二条保留
    base_evidence = {
        "skill": [
            {"text": "匹配到 Python", "source": "skills", "offset": [0, 6]},
            {"text": "匹配到 Go", "source": "skills", "offset": [8, 10]},
        ],
        "experience": [], "seniority": [], "education": [], "industry": [],
    }
    with patch("app.modules.matching.scorers.evidence._call_llm",
               new=AsyncMock(return_value={"skill": ["Python 强匹配"]})):
        result = await enhance_evidence_with_llm(base_evidence, _FakeResume(), dim_scores={})

    assert result["skill"][0]["text"] == "Python 强匹配"
    assert result["skill"][1]["text"] == "匹配到 Go"
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_evidence_llm_fallback.py -v`
Expected: `ImportError: enhance_evidence_with_llm`

- [ ] **Step 3: 扩 evidence.py 加 LLM 增强**

Append to `app/modules/matching/scorers/evidence.py`:

```python
import json
import logging
from app.config import settings
from app.core.llm.parsing import extract_json
from app.core.llm.provider import LLMError, LLMProvider

_logger = logging.getLogger(__name__)

_EVIDENCE_PROMPT = """你是招聘简历评估专家。给定一份简历摘要和 5 维度匹配分，每维度生成 1-3 条自然语言证据片段。
每条 ≤ 30 字。只输出 JSON，字段为 skill/experience/seniority/education/industry, 值为字符串数组。
简历：{resume_name}（技能：{skills}）
分数：{dim_scores}
现有 deterministic 证据：{base_evidence}"""


async def _call_llm(prompt: str) -> dict:
    """发起 LLM 调用, 返回解析后的 dict. 失败抛 LLMError."""
    provider = LLMProvider()
    content = await provider.complete(
        messages=[{"role": "user", "content": prompt}],
        prompt_version="f2_evidence_v1",
        f_stage="F2",
        entity_type="matching_result",
        temperature=0.3,
        response_format="json",
    )
    return extract_json(content)


async def enhance_evidence_with_llm(
    base_evidence: dict,
    resume: Any,
    dim_scores: dict,
) -> dict:
    """把 LLM 生成的 text 覆盖到 base_evidence 对应项, source/offset 保留.
    LLM 失败时直接返回 base_evidence 不抛.
    """
    if not getattr(settings, "matching_evidence_llm_enabled", True):
        return base_evidence

    try:
        prompt = _EVIDENCE_PROMPT.format(
            resume_name=getattr(resume, "name", ""),
            skills=getattr(resume, "skills", ""),
            dim_scores=json.dumps(dim_scores, ensure_ascii=False),
            base_evidence=json.dumps(
                {k: [e["text"] for e in v] for k, v in base_evidence.items()},
                ensure_ascii=False,
            ),
        )
        llm_out = await _call_llm(prompt)
    except LLMError as e:
        _logger.info(f"LLM evidence failed, using deterministic only: {e}")
        return base_evidence
    except Exception as e:
        _logger.warning(f"LLM evidence unexpected error: {e}")
        return base_evidence

    # 覆盖 text, 保留 source/offset
    for dim, texts in (llm_out or {}).items():
        if dim not in base_evidence:
            continue
        for i, text in enumerate(texts or []):
            if i < len(base_evidence[dim]):
                base_evidence[dim][i]["text"] = text

    return base_evidence
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_evidence_llm_fallback.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/scorers/evidence.py tests/modules/matching/test_evidence_llm_fallback.py
git commit -m "feat(f2): LLM evidence enhancement with graceful fallback"
```

---

## Task 12: Config 配置项

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: 加 5 个 F2 配置项**

Modify `app/config.py` — 在 Settings 类内加（放 ai_enabled 等既有配置附近）：

```python
    matching_enabled: bool = True
    matching_evidence_llm_enabled: bool = True
    matching_trigger_days_back: int = 90
    matching_skill_sim_exact: float = 0.75
    matching_skill_sim_edge: float = 0.60
    matching_industry_sim: float = 0.70
```

- [ ] **Step 2: 跑全量测试验零回归**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/ -x --tb=short -q`
Expected: 全部 pass

- [ ] **Step 3: Commit**

```bash
cd D:/libz/AgenticHR
git add app/config.py
git commit -m "feat(f2): config flags for matching module"
```

---

## Task 13: Pydantic 响应 schemas

**Files:**
- Create: `app/modules/matching/schemas.py`
- Test: `tests/modules/matching/test_schemas.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_schemas.py`:

```python
from app.modules.matching.schemas import (
    EvidenceItem, MatchingResultResponse,
    ScoreRequest, RecomputeRequest, RecomputeStatus,
)


def test_evidence_item_with_offset():
    item = EvidenceItem(text="匹配到 Python", source="skills", offset=[0, 6])
    assert item.offset == [0, 6]


def test_evidence_item_null_offset():
    item = EvidenceItem(text="工作年限 5 年", source="work_years", offset=None)
    assert item.offset is None


def test_score_request_valid():
    req = ScoreRequest(resume_id=1, job_id=2)
    assert req.resume_id == 1


def test_recompute_request_job_id():
    req = RecomputeRequest(job_id=2)
    assert req.job_id == 2
    assert req.resume_id is None


def test_recompute_request_resume_id():
    req = RecomputeRequest(resume_id=5)
    assert req.resume_id == 5
    assert req.job_id is None


def test_recompute_status_shape():
    s = RecomputeStatus(task_id="x", total=10, completed=3, failed=0, running=True, current="Job#2 × Resume#5")
    assert s.running is True
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_schemas.py -v`
Expected: `ImportError`

- [ ] **Step 3: 写实现**

Create `app/modules/matching/schemas.py`:

```python
"""F2 API 请求/响应 Pydantic schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    text: str
    source: str = ""
    offset: list[int] | None = None


class MatchingResultResponse(BaseModel):
    id: int
    resume_id: int
    resume_name: str = ""
    job_id: int
    job_title: str = ""

    total_score: float
    skill_score: float
    experience_score: float
    seniority_score: float
    education_score: float
    industry_score: float

    hard_gate_passed: bool
    missing_must_haves: list[str] = []

    evidence: dict[str, list[EvidenceItem]] = Field(default_factory=dict)
    tags: list[str] = []

    stale: bool = False
    scored_at: datetime


class MatchingResultListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[MatchingResultResponse]


class ScoreRequest(BaseModel):
    resume_id: int
    job_id: int


class RecomputeRequest(BaseModel):
    job_id: int | None = None
    resume_id: int | None = None


class RecomputeStatus(BaseModel):
    task_id: str
    total: int
    completed: int
    failed: int
    running: bool
    current: str = ""
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_schemas.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/schemas.py tests/modules/matching/test_schemas.py
git commit -m "feat(f2): pydantic schemas for matching API"
```

---

## Task 14: MatchingService.score_pair 编排

**Files:**
- Create: `app/modules/matching/service.py`
- Test: `tests/modules/matching/test_service.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_service.py`:

```python
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from app.modules.matching.service import MatchingService
from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _seed_resume(session, **overrides):
    kw = dict(
        name="张三", phone="13900000001", email="t@test.com",
        skills="Python, Go, FastAPI", work_experience="在某互联网公司任后端 5 年",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
    )
    kw.update(overrides)
    r = Resume(**kw)
    session.add(r); session.commit()
    return r


def _seed_job_with_competency(session, competency_model: dict, **overrides):
    kw = dict(
        title="后端工程师", status="open",
        education_min="本科", work_years_min=3, work_years_max=8,
        required_skills="Python",
        competency_model=competency_model,
        competency_model_status="approved",
    )
    kw.update(overrides)
    j = Job(**kw)
    session.add(j); session.commit()
    return j


@pytest.mark.asyncio
async def test_score_pair_writes_row(db_session):
    resume = _seed_resume(db_session)
    cm = {
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 8, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    }
    job = _seed_job_with_competency(db_session, cm)

    service = MatchingService(db_session)
    with patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.95), \
         patch("app.modules.matching.service.enhance_evidence_with_llm", new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        result = await service.score_pair(resume.id, job.id)

    row = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
    assert row.total_score == result.total_score
    assert row.hard_gate_passed == 1
    assert row.skill_score > 0


@pytest.mark.asyncio
async def test_score_pair_upserts(db_session):
    resume = _seed_resume(db_session)
    cm = {"hard_skills": [], "experience": {"years_min": 3, "years_max": 8},
          "education": {"min_level": "本科"}, "job_level": "中级"}
    job = _seed_job_with_competency(db_session, cm)

    service = MatchingService(db_session)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        r1 = await service.score_pair(resume.id, job.id)
        r2 = await service.score_pair(resume.id, job.id)

    count = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).count()
    assert count == 1
    assert r2.id == r1.id


@pytest.mark.asyncio
async def test_score_pair_hard_gate_missing(db_session):
    resume = _seed_resume(db_session, skills="Java")
    cm = {
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 8},
        "education": {"min_level": "本科"}, "job_level": "高级",
    }
    job = _seed_job_with_competency(db_session, cm)

    service = MatchingService(db_session)
    with patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.2), \
         patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        result = await service.score_pair(resume.id, job.id)

    assert result.hard_gate_passed is False
    assert "Python" in result.missing_must_haves
    assert result.total_score <= 29.0


@pytest.mark.asyncio
async def test_score_pair_raises_on_missing_resume(db_session):
    with pytest.raises(ValueError, match="resume"):
        await MatchingService(db_session).score_pair(99999, 1)
```

Note: `pytest-asyncio` 应该已经装了（F1 有异步测试），如果没装：`pip install pytest-asyncio` 并在 `pyproject.toml` 加 `[tool.pytest.ini_options]\nasyncio_mode = "auto"`.

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_service.py -v`
Expected: `ImportError: MatchingService`

- [ ] **Step 3: 写 MatchingService**

Create `app/modules/matching/service.py`:

```python
"""F2 匹配服务 — 编排 scorers + 写 DB + 审计."""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.audit.logger import log_event
from app.core.settings.router import _load as _load_scoring_weights
from app.modules.matching.hashing import compute_competency_hash, compute_weights_hash
from app.modules.matching.models import MatchingResult
from app.modules.matching.schemas import EvidenceItem, MatchingResultResponse
from app.modules.matching.scorers.aggregator import aggregate, derive_tags
from app.modules.matching.scorers.education import score_education
from app.modules.matching.scorers.evidence import (
    build_deterministic_evidence, enhance_evidence_with_llm,
)
from app.modules.matching.scorers.experience import score_experience
from app.modules.matching.scorers.industry import score_industry
from app.modules.matching.scorers.seniority import score_seniority
from app.modules.matching.scorers.skill import score_skill, _parse_resume_skills
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class MatchingService:
    def __init__(self, db: Session):
        self.db = db

    async def score_pair(
        self, resume_id: int, job_id: int, *, triggered_by: str = "T4"
    ) -> MatchingResultResponse:
        resume = self.db.query(Resume).filter_by(id=resume_id).first()
        if not resume:
            raise ValueError(f"resume {resume_id} not found")
        job = self.db.query(Job).filter_by(id=job_id).first()
        if not job:
            raise ValueError(f"job {job_id} not found")
        if not job.competency_model:
            raise ValueError(f"job {job_id} has no competency_model (not approved yet)")

        cm = job.competency_model
        weights = _load_scoring_weights()

        # 分维度打分
        skill_score, missing_must = score_skill(
            cm.get("hard_skills", []),
            resume.skills or "",
            db_session=self.db,
        )
        experience_score = score_experience(
            resume.work_years or 0,
            cm.get("experience") or {},
        )
        seniority_score = score_seniority(
            resume.seniority or "",
            cm.get("job_level", "") or "",
        )
        education_score = score_education(
            resume.education or "",
            cm.get("education") or {},
        )
        industries = (cm.get("experience") or {}).get("industries") or []
        industry_score = score_industry(
            resume.work_experience or "", industries, db_session=self.db,
        )

        # 聚合
        agg = aggregate(
            dim_scores={
                "skill": skill_score, "experience": experience_score,
                "seniority": seniority_score, "education": education_score,
                "industry": industry_score,
            },
            missing_must_haves=missing_must,
            weights=weights,
        )
        tags = derive_tags(
            total_score=agg["total_score"],
            hard_gate_passed=agg["hard_gate_passed"],
            missing=missing_must,
            education_score=education_score,
            experience_score=experience_score,
        )

        # 证据
        matched_skills = self._compute_matched_skills(cm.get("hard_skills", []), resume, missing_must)
        matched_industries = self._compute_matched_industries(industries, resume.work_experience or "")
        base_ev = build_deterministic_evidence(
            resume=resume,
            matched_skills=matched_skills,
            experience_range=(
                (cm.get("experience") or {}).get("years_min", 0),
                (cm.get("experience") or {}).get("years_max") or ((cm.get("experience") or {}).get("years_min", 0) + 10),
            ),
            matched_industries=matched_industries,
        )
        dim_scores_dict = {
            "skill": skill_score, "experience": experience_score,
            "seniority": seniority_score, "education": education_score,
            "industry": industry_score,
        }
        evidence = await enhance_evidence_with_llm(base_ev, resume, dim_scores_dict)

        # UPSERT
        competency_hash = compute_competency_hash(cm)
        weights_hash = compute_weights_hash(weights)
        now = datetime.now(timezone.utc)

        existing = self.db.query(MatchingResult).filter_by(
            resume_id=resume_id, job_id=job_id
        ).first()
        if existing:
            existing.total_score = agg["total_score"]
            existing.skill_score = skill_score
            existing.experience_score = experience_score
            existing.seniority_score = seniority_score
            existing.education_score = education_score
            existing.industry_score = industry_score
            existing.hard_gate_passed = 1 if agg["hard_gate_passed"] else 0
            existing.missing_must_haves = json.dumps(missing_must, ensure_ascii=False)
            existing.evidence = json.dumps(evidence, ensure_ascii=False)
            existing.tags = json.dumps(tags, ensure_ascii=False)
            existing.competency_hash = competency_hash
            existing.weights_hash = weights_hash
            existing.scored_at = now
            row = existing
        else:
            row = MatchingResult(
                resume_id=resume_id, job_id=job_id,
                total_score=agg["total_score"],
                skill_score=skill_score, experience_score=experience_score,
                seniority_score=seniority_score, education_score=education_score,
                industry_score=industry_score,
                hard_gate_passed=1 if agg["hard_gate_passed"] else 0,
                missing_must_haves=json.dumps(missing_must, ensure_ascii=False),
                evidence=json.dumps(evidence, ensure_ascii=False),
                tags=json.dumps(tags, ensure_ascii=False),
                competency_hash=competency_hash, weights_hash=weights_hash,
                scored_at=now,
            )
            self.db.add(row)

        self.db.commit()
        self.db.refresh(row)

        # 审计
        try:
            log_event(
                f_stage="F2",
                action="score",
                entity_type="matching_result",
                entity_id=row.id,
                input_payload={
                    "resume_id": resume_id, "job_id": job_id,
                    "trigger": triggered_by,
                    "competency_hash": competency_hash,
                    "weights_hash": weights_hash,
                },
                output_payload={
                    "total_score": agg["total_score"],
                    "dim_scores": dim_scores_dict,
                    "tags": tags,
                    "hard_gate_passed": agg["hard_gate_passed"],
                    "missing_must_haves": missing_must,
                },
            )
        except Exception as e:
            logger.warning(f"audit log failed (non-fatal): {e}")

        return self._to_response(row, resume, job, competency_hash, weights_hash)

    @staticmethod
    def _compute_matched_skills(hard_skills: list[dict], resume: Resume, missing: list[str]) -> list[str]:
        """匹配到的技能名 = hard_skills - missing."""
        missing_set = set(missing)
        return [hs["name"] for hs in hard_skills if hs.get("name") not in missing_set]

    @staticmethod
    def _compute_matched_industries(industries: list[str], work_experience: str) -> list[str]:
        text = (work_experience or "").lower()
        return [ind for ind in industries if ind and ind.lower() in text]

    @staticmethod
    def _to_response(
        row: MatchingResult, resume: Resume, job: Job,
        current_competency_hash: str, current_weights_hash: str,
    ) -> MatchingResultResponse:
        evidence_dict = json.loads(row.evidence or "{}")
        return MatchingResultResponse(
            id=row.id, resume_id=row.resume_id, resume_name=resume.name,
            job_id=row.job_id, job_title=job.title,
            total_score=row.total_score, skill_score=row.skill_score,
            experience_score=row.experience_score, seniority_score=row.seniority_score,
            education_score=row.education_score, industry_score=row.industry_score,
            hard_gate_passed=bool(row.hard_gate_passed),
            missing_must_haves=json.loads(row.missing_must_haves or "[]"),
            evidence={k: [EvidenceItem(**e) for e in v] for k, v in evidence_dict.items()},
            tags=json.loads(row.tags or "[]"),
            stale=(row.competency_hash != current_competency_hash
                   or row.weights_hash != current_weights_hash),
            scored_at=row.scored_at,
        )
```

- [ ] **Step 4: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_service.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/service.py tests/modules/matching/test_service.py
git commit -m "feat(f2): MatchingService.score_pair orchestration (UPSERT + audit)"
```

---

## Task 15: Router — score + results endpoints

**Files:**
- Create: `app/modules/matching/router.py`
- Modify: `app/main.py` — 注册 router
- Test: `tests/modules/matching/test_router_score.py`
- Test: `tests/modules/matching/test_router_results.py`

- [ ] **Step 1: 写 router_score 失败测试**

Create `tests/modules/matching/test_router_score.py`:

```python
from unittest.mock import patch, AsyncMock


def test_score_endpoint_returns_result(client, db_session):
    from app.modules.resume.models import Resume
    from app.modules.screening.models import Job
    resume = Resume(name="张三", phone="13900000001", email="t@test.com",
                    skills="Python", work_years=5, education="本科",
                    ai_parsed="yes", source="manual", seniority="高级")
    db_session.add(resume); db_session.commit()
    cm = {"hard_skills": [], "experience": {"years_min": 3, "years_max": 8},
          "education": {"min_level": "本科"}, "job_level": "高级"}
    job = Job(title="后端", status="open", required_skills="",
              competency_model=cm, competency_model_status="approved")
    db_session.add(job); db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/score",
                            json={"resume_id": resume.id, "job_id": job.id})

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume.id
    assert data["job_id"] == job.id
    assert "total_score" in data
    assert "evidence" in data


def test_score_endpoint_404_on_missing(client):
    resp = client.post("/api/matching/score", json={"resume_id": 99999, "job_id": 99999})
    assert resp.status_code == 404
```

- [ ] **Step 2: 写 router_results 失败测试**

Create `tests/modules/matching/test_router_results.py`:

```python
from datetime import datetime, timezone
from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _seed_data(session, count: int = 3):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", status="open", required_skills="",
              competency_model=cm, competency_model_status="approved")
    session.add(job); session.commit()

    for i in range(count):
        r = Resume(name=f"候选人{i}", phone="13900000000",
                   skills="Python", work_years=3, education="本科",
                   ai_parsed="yes", source="manual", seniority="中级")
        session.add(r); session.commit()
        session.add(MatchingResult(
            resume_id=r.id, job_id=job.id,
            total_score=90 - i * 10, skill_score=90 - i * 10,
            experience_score=80, seniority_score=80, education_score=80, industry_score=80,
            hard_gate_passed=1, missing_must_haves="[]",
            evidence="{}", tags='["中匹配"]',
            competency_hash="h1", weights_hash="h2",
            scored_at=datetime.now(timezone.utc),
        )); session.commit()
    return job


def test_results_by_job_sorted_desc(client, db_session):
    job = _seed_data(db_session, count=3)
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    scores = [it["total_score"] for it in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_results_by_resume(client, db_session):
    job = _seed_data(db_session, count=1)
    resume_id = db_session.query(MatchingResult).first().resume_id
    resp = client.get(f"/api/matching/results?resume_id={resume_id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_results_filter_by_tag(client, db_session):
    _seed_data(db_session, count=3)
    resp = client.get("/api/matching/results?job_id=1&tag=中匹配")
    assert resp.status_code == 200
    assert resp.json()["total"] == 3


def test_results_pagination(client, db_session):
    _seed_data(db_session, count=5)
    resp = client.get("/api/matching/results?job_id=1&page=1&page_size=2")
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1


def test_stale_flag_true_when_hash_mismatch(client, db_session):
    job = _seed_data(db_session, count=1)
    # job.competency_model 的当前 hash 与 seed 的 "h1" 不一致 → 应为 stale
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    data = resp.json()
    assert data["items"][0]["stale"] is True
```

- [ ] **Step 3: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_router_score.py tests/modules/matching/test_router_results.py -v`
Expected: 404 或 ImportError

- [ ] **Step 4: 写 router.py（score + results 两个端点）**

Create `app/modules/matching/router.py`:

```python
"""F2 匹配 REST API."""
import json
import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.settings.router import _load as _load_scoring_weights
from app.database import get_db
from app.modules.matching.hashing import compute_competency_hash, compute_weights_hash
from app.modules.matching.models import MatchingResult
from app.modules.matching.schemas import (
    EvidenceItem,
    MatchingResultResponse, MatchingResultListResponse,
    ScoreRequest, RecomputeRequest, RecomputeStatus,
)
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/matching", tags=["matching"])


def _require_matching_enabled():
    if not getattr(settings, "matching_enabled", True):
        raise HTTPException(status_code=503, detail="matching feature disabled")


@router.post("/score", response_model=MatchingResultResponse)
async def score_pair(req: ScoreRequest, db: Session = Depends(get_db)):
    _require_matching_enabled()
    service = MatchingService(db)
    try:
        return await service.score_pair(req.resume_id, req.job_id, triggered_by="T4")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/results", response_model=MatchingResultListResponse)
def list_results(
    job_id: Optional[int] = None,
    resume_id: Optional[int] = None,
    tag: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _require_matching_enabled()
    if not job_id and not resume_id:
        raise HTTPException(status_code=400, detail="need job_id or resume_id")

    q = db.query(MatchingResult)
    if job_id:
        q = q.filter_by(job_id=job_id).order_by(MatchingResult.total_score.desc())
    if resume_id:
        q = q.filter_by(resume_id=resume_id).order_by(MatchingResult.total_score.desc())

    all_rows = q.all()
    if tag:
        all_rows = [r for r in all_rows if tag in json.loads(r.tags or "[]")]

    total = len(all_rows)
    start = (page - 1) * page_size
    rows = all_rows[start: start + page_size]

    # 批量预取 resume/job 信息 + 当前 hash
    resume_ids = {r.resume_id for r in rows}
    job_ids = {r.job_id for r in rows}
    resumes = {r.id: r for r in db.query(Resume).filter(Resume.id.in_(resume_ids)).all()}
    jobs = {j.id: j for j in db.query(Job).filter(Job.id.in_(job_ids)).all()}

    # Group by job for hash compute
    current_hashes = {}   # job_id → (competency_hash, weights_hash)
    weights_hash = compute_weights_hash(_load_scoring_weights())
    for jid, j in jobs.items():
        current_hashes[jid] = (compute_competency_hash(j.competency_model or {}), weights_hash)

    items = []
    for r in rows:
        resume = resumes.get(r.resume_id)
        job = jobs.get(r.job_id)
        current_c, current_w = current_hashes.get(r.job_id, (r.competency_hash, r.weights_hash))
        evidence_dict = json.loads(r.evidence or "{}")
        items.append(MatchingResultResponse(
            id=r.id, resume_id=r.resume_id,
            resume_name=resume.name if resume else "",
            job_id=r.job_id, job_title=job.title if job else "",
            total_score=r.total_score, skill_score=r.skill_score,
            experience_score=r.experience_score, seniority_score=r.seniority_score,
            education_score=r.education_score, industry_score=r.industry_score,
            hard_gate_passed=bool(r.hard_gate_passed),
            missing_must_haves=json.loads(r.missing_must_haves or "[]"),
            evidence={k: [EvidenceItem(**e) for e in v] for k, v in evidence_dict.items()},
            tags=json.loads(r.tags or "[]"),
            stale=(r.competency_hash != current_c or r.weights_hash != current_w),
            scored_at=r.scored_at,
        ))
    return MatchingResultListResponse(
        total=total, page=page, page_size=page_size, items=items,
    )
```

- [ ] **Step 5: 注册 router 到 main.py**

Modify `app/main.py` — 找到既有 router 注册（如 `app.include_router(ai_evaluation_router, ...)`），加一行：

```python
from app.modules.matching.router import router as matching_router
app.include_router(matching_router)
```

- [ ] **Step 6: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_router_score.py tests/modules/matching/test_router_results.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/router.py app/main.py tests/modules/matching/test_router_score.py tests/modules/matching/test_router_results.py
git commit -m "feat(f2): /api/matching/score + /api/matching/results endpoints"
```

---

## Task 16: Router — recompute（异步批量）+ 任务进度

**Files:**
- Modify: `app/modules/matching/router.py`
- Modify: `app/modules/matching/service.py`
- Test: `tests/modules/matching/test_router_recompute.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_router_recompute.py`:

```python
import time
from unittest.mock import patch, AsyncMock
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _seed(session, n_resumes=3):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", status="open", required_skills="",
              competency_model=cm, competency_model_status="approved")
    session.add(job); session.commit()

    for i in range(n_resumes):
        r = Resume(name=f"R{i}", phone="", skills="Python", work_years=2,
                   education="本科", ai_parsed="yes", source="manual", seniority="中级")
        session.add(r); session.commit()
    return job


def test_recompute_job_returns_task_id(client, db_session):
    job = _seed(db_session, n_resumes=2)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["total"] >= 2


def test_recompute_status_endpoint(client, db_session):
    job = _seed(db_session, n_resumes=1)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    task_id = resp.json()["task_id"]

    # 等任务跑完（同步 BackgroundTasks 实际在 TestClient 下会阻塞到结束）
    time.sleep(0.1)
    status_resp = client.get(f"/api/matching/recompute/status/{task_id}")
    assert status_resp.status_code == 200
    s = status_resp.json()
    assert s["task_id"] == task_id
    assert s["total"] >= 1


def test_recompute_validates_one_of():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.post("/api/matching/recompute", json={})
    assert resp.status_code == 400
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_router_recompute.py -v`
Expected: 404 (endpoint missing)

- [ ] **Step 3: 在 service.py 加 recompute 方法**

Append to `app/modules/matching/service.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

# 全局任务状态表（in-memory，进程重启丢；足够 V1 用）
_RECOMPUTE_TASKS: dict[str, dict] = {}


def _new_task(total: int) -> str:
    task_id = str(uuid.uuid4())
    _RECOMPUTE_TASKS[task_id] = {
        "task_id": task_id, "total": total, "completed": 0, "failed": 0,
        "running": True, "current": "",
        "started_at": datetime.now(timezone.utc),
    }
    return task_id


def _get_task(task_id: str) -> dict | None:
    return _RECOMPUTE_TASKS.get(task_id)


def _prune_stale_tasks(hours: int = 24) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stale = [k for k, v in _RECOMPUTE_TASKS.items() if v["started_at"] < cutoff]
    for k in stale:
        _RECOMPUTE_TASKS.pop(k, None)


async def recompute_job(db: Session, job_id: int, task_id: str) -> None:
    """后台任务：对 job 的所有 ai_parsed='yes' 简历打分."""
    task = _RECOMPUTE_TASKS[task_id]
    try:
        resume_ids = [r.id for r in db.query(Resume).filter_by(ai_parsed="yes").all()]
        task["total"] = len(resume_ids)
        service = MatchingService(db)
        for rid in resume_ids:
            task["current"] = f"Resume#{rid} × Job#{job_id}"
            try:
                await service.score_pair(rid, job_id, triggered_by="T3")
                task["completed"] += 1
            except Exception as e:
                logger.warning(f"recompute failed for resume {rid}: {e}")
                task["failed"] += 1
    finally:
        task["running"] = False
        task["current"] = ""


async def recompute_resume(db: Session, resume_id: int, task_id: str) -> None:
    """后台任务：对 resume 的所有 open + approved 岗位打分."""
    task = _RECOMPUTE_TASKS[task_id]
    try:
        job_ids = [j.id for j in db.query(Job).filter_by(
            status="open", competency_model_status="approved"
        ).all()]
        task["total"] = len(job_ids)
        service = MatchingService(db)
        for jid in job_ids:
            task["current"] = f"Resume#{resume_id} × Job#{jid}"
            try:
                await service.score_pair(resume_id, jid, triggered_by="T3")
                task["completed"] += 1
            except Exception as e:
                logger.warning(f"recompute failed for job {jid}: {e}")
                task["failed"] += 1
    finally:
        task["running"] = False
        task["current"] = ""
```

- [ ] **Step 4: router.py 加 recompute + status 端点**

Append to `app/modules/matching/router.py`:

```python
from fastapi import BackgroundTasks
from app.modules.matching.service import (
    _new_task, _get_task, _prune_stale_tasks,
    recompute_job, recompute_resume,
)


@router.post("/recompute")
async def post_recompute(
    req: RecomputeRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    _require_matching_enabled()
    _prune_stale_tasks()
    if not req.job_id and not req.resume_id:
        raise HTTPException(status_code=400, detail="need job_id or resume_id")

    if req.job_id:
        total = db.query(Resume).filter_by(ai_parsed="yes").count()
        task_id = _new_task(total)
        background.add_task(recompute_job, db, req.job_id, task_id)
        return {"task_id": task_id, "total": total}

    total = db.query(Job).filter_by(status="open", competency_model_status="approved").count()
    task_id = _new_task(total)
    background.add_task(recompute_resume, db, req.resume_id, task_id)
    return {"task_id": task_id, "total": total}


@router.get("/recompute/status/{task_id}", response_model=RecomputeStatus)
def get_recompute_status(task_id: str):
    task = _get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return RecomputeStatus(
        task_id=task["task_id"], total=task["total"],
        completed=task["completed"], failed=task["failed"],
        running=task["running"], current=task.get("current", ""),
    )
```

- [ ] **Step 5: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_router_recompute.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/router.py app/modules/matching/service.py tests/modules/matching/test_router_recompute.py
git commit -m "feat(f2): /api/matching/recompute async task + status polling"
```

---

## Task 17: Triggers — T1（简历入库）+ T2（能力模型发布）

**Files:**
- Create: `app/modules/matching/triggers.py`
- Modify: `app/modules/resume/service.py` — `_ai_parse_worker` 完成时调 T1
- Modify: `app/modules/screening/router.py` — approve handler 末尾调 T2
- Test: `tests/integration/test_f2_trigger_resume_ingest.py`
- Test: `tests/integration/test_f2_trigger_competency_approve.py`

- [ ] **Step 1: 创建 integration 测试目录**

Create empty `tests/integration/__init__.py` if missing.

- [ ] **Step 2: 写 T1 失败测试**

Create `tests/integration/test_f2_trigger_resume_ingest.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.triggers import on_resume_parsed
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _mk_open_job(session, title="Job"):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    j = Job(title=title, status="open", required_skills="",
            competency_model=cm, competency_model_status="approved")
    session.add(j); session.commit()
    return j


@pytest.mark.asyncio
async def test_on_resume_parsed_scores_all_open_approved_jobs(db_session):
    _mk_open_job(db_session, "Job A")
    _mk_open_job(db_session, "Job B")
    # 未发布的能力模型不应被打分
    unapproved = Job(title="Draft", status="open", required_skills="",
                     competency_model={"hard_skills": []}, competency_model_status="draft")
    db_session.add(unapproved); db_session.commit()
    # 关闭的岗位不应被打分
    closed = Job(title="Closed", status="closed", required_skills="",
                 competency_model={"hard_skills": []}, competency_model_status="approved")
    db_session.add(closed); db_session.commit()

    r = Resume(name="张三", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_resume_parsed(db_session, r.id)

    rows = db_session.query(MatchingResult).filter_by(resume_id=r.id).all()
    assert len(rows) == 2  # 只有 open + approved 的两个
```

- [ ] **Step 3: 写 T2 失败测试**

Create `tests/integration/test_f2_trigger_competency_approve.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.triggers import on_competency_approved
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_on_competency_approved_scores_recent_resumes(db_session):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    j = Job(title="后端", status="open", required_skills="",
            competency_model=cm, competency_model_status="approved")
    db_session.add(j); db_session.commit()

    # 最近 30 天内的简历
    recent = Resume(name="Recent", phone="", skills="Python", work_years=3,
                    education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(recent); db_session.commit()

    # 老于 90 天的简历（手动调 created_at）
    old = Resume(name="Old", phone="", skills="Python", work_years=3,
                 education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(old); db_session.commit()
    old.created_at = datetime.now(timezone.utc) - timedelta(days=120)
    db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_competency_approved(db_session, j.id)

    rows = db_session.query(MatchingResult).filter_by(job_id=j.id).all()
    assert len(rows) == 1
    assert rows[0].resume_id == recent.id
```

- [ ] **Step 4: 写 triggers 实现**

Create `app/modules/matching/triggers.py`:

```python
"""F2 触发器 — T1 简历入库 / T2 能力模型发布."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


async def on_resume_parsed(db: Session, resume_id: int) -> None:
    """T1: 简历 AI 解析完成 → 对所有 open + approved 岗位打分."""
    if not getattr(settings, "matching_enabled", True):
        return
    jobs = db.query(Job).filter(
        Job.status == "open",
        Job.competency_model_status == "approved",
    ).all()
    service = MatchingService(db)
    for job in jobs:
        try:
            await service.score_pair(resume_id, job.id, triggered_by="T1")
        except Exception as e:
            logger.warning(f"T1 score failed resume={resume_id} job={job.id}: {e}")


async def on_competency_approved(db: Session, job_id: int) -> None:
    """T2: 能力模型发布 → 对过去 N 天入库的 ai_parsed='yes' 简历打分."""
    if not getattr(settings, "matching_enabled", True):
        return
    days = getattr(settings, "matching_trigger_days_back", 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    resumes = db.query(Resume).filter(
        Resume.ai_parsed == "yes",
        Resume.created_at >= cutoff,
    ).all()
    service = MatchingService(db)
    for r in resumes:
        try:
            await service.score_pair(r.id, job_id, triggered_by="T2")
        except Exception as e:
            logger.warning(f"T2 score failed resume={r.id} job={job_id}: {e}")
```

- [ ] **Step 5: 验证 trigger 测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/integration/test_f2_trigger_resume_ingest.py tests/integration/test_f2_trigger_competency_approve.py -v`
Expected: 2 passed

- [ ] **Step 6: 在 resume service 钩子里调 T1**

在 `app/modules/resume/service.py` 找到 AI 解析成功写 `ai_parsed='yes'` 的位置，末尾加：

```python
# F2: trigger scoring in background
try:
    import asyncio
    from app.modules.matching.triggers import on_resume_parsed
    asyncio.create_task(on_resume_parsed(db, resume.id))
except Exception as e:
    logger.warning(f"F2 trigger failed: {e}")
```

（具体位置以 `_ai_parse_worker.py` 或 service.py 中处理完 `ai_parsed="yes"` 提交的地方为准；如果 `_ai_parse_worker` 使用非同步逻辑，改用合适的 await/fire-and-forget 模式。）

- [ ] **Step 7: 在 screening approve handler 里调 T2**

在 `app/modules/screening/router.py` 找到 `competency_model_status = "approved"` 提交后的位置（约 line 360 附近 `apply_competency_to_job`），在 commit 之后加：

```python
# F2: trigger scoring for recent resumes
try:
    from app.modules.matching.triggers import on_competency_approved
    background_tasks.add_task(on_competency_approved, db, job_id)
except Exception as e:
    logger.warning(f"F2 T2 trigger failed: {e}")
```

（需要在 endpoint 签名加 `background_tasks: BackgroundTasks`；查看 screening/router.py 对应 handler 的函数签名。）

- [ ] **Step 8: 跑全量测试**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/ -x --tb=short -q`
Expected: 全部 pass

- [ ] **Step 9: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/matching/triggers.py app/modules/resume/service.py app/modules/screening/router.py tests/integration/
git commit -m "feat(f2): T1 resume-ingest + T2 competency-approve triggers"
```

---

## Task 18: 废弃旧 ai_evaluation/evaluate*（返 410 Gone）

**Files:**
- Modify: `app/modules/ai_evaluation/router.py`
- Modify: `app/modules/ai_evaluation/service.py`
- Modify: `app/modules/ai_evaluation/schemas.py`
- Test: `tests/modules/matching/test_deprecated_evaluate.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/matching/test_deprecated_evaluate.py`:

```python
def test_evaluate_returns_410(client):
    resp = client.post("/api/ai-evaluation/evaluate",
                       json={"resume_id": 1, "job_id": 2})
    assert resp.status_code == 410
    body = resp.json()
    assert "migrate_to" in body.get("detail", {}) or "migrate_to" in body


def test_evaluate_batch_returns_410(client):
    resp = client.post("/api/ai-evaluation/evaluate/batch", json={"job_id": 1})
    assert resp.status_code == 410


def test_status_still_ok(client):
    resp = client.get("/api/ai-evaluation/status")
    assert resp.status_code == 200
```

- [ ] **Step 2: 验证测试失败**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_deprecated_evaluate.py -v`
Expected: 2 failed (endpoints 还在)

- [ ] **Step 3: 改 router.py 让 /evaluate 返 410**

Overwrite `app/modules/ai_evaluation/router.py`:

```python
"""AI 评估 API (F5 will extend)."""
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.adapters.ai_provider import AIProvider

router = APIRouter()


@router.post("/evaluate")
async def deprecated_evaluate_single():
    raise HTTPException(
        status_code=410,
        detail={
            "msg": "/api/ai-evaluation/evaluate has been removed in favor of F2 structured matching.",
            "migrate_to": "/api/matching/score",
        },
    )


@router.post("/evaluate/batch")
async def deprecated_evaluate_batch():
    raise HTTPException(
        status_code=410,
        detail={
            "msg": "/api/ai-evaluation/evaluate/batch has been removed in favor of F2 structured matching.",
            "migrate_to": "/api/matching/recompute",
        },
    )


@router.get("/status")
def ai_status():
    provider = AIProvider()
    return {
        "enabled": settings.ai_enabled,
        "configured": provider.is_configured(),
        "provider": settings.ai_provider,
        "model": settings.ai_model,
    }
```

- [ ] **Step 4: 删除 service.py 中的 evaluate_single / evaluate_batch**

Overwrite `app/modules/ai_evaluation/service.py`:

```python
"""AI 评估 service (F5 will implement synthesis logic on top of F2 matching)."""
# F2 废弃了 evaluate_single / evaluate_batch 这两个方法 - 参见 /api/matching/*
```

- [ ] **Step 5: 清理 schemas.py（删 EvaluationRequest 等）**

Overwrite `app/modules/ai_evaluation/schemas.py`:

```python
"""AI 评估 schemas. F2 废弃 EvaluationRequest/Response, F5 扩展时会新增."""
```

- [ ] **Step 6: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/matching/test_deprecated_evaluate.py -v`
Expected: 3 passed

- [ ] **Step 7: 跑全量确认没有其他地方依赖删掉的函数**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/ -x --tb=short -q`
Expected: 全部 pass

如失败出现 `ImportError: cannot import name 'evaluate_single'` 等，找到依赖方改接 MatchingService 或删除对应测试。

- [ ] **Step 8: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/ai_evaluation/ tests/modules/matching/test_deprecated_evaluate.py
git commit -m "feat(f2): deprecate /ai-evaluation/evaluate* with 410 + migrate_to hint"
```

---

## Task 19: Resume.seniority 在 _ai_parse_worker 里推断

**Files:**
- Modify: `app/modules/resume/_ai_parse_worker.py`
- Modify: `app/modules/resume/schemas.py` — ResumeResponse 加 seniority

- [ ] **Step 1: 读现有 _ai_parse_worker 结构**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/python -c "from app.modules.resume import _ai_parse_worker; print([n for n in dir(_ai_parse_worker) if not n.startswith('_')])"`
Expected: 列出所有公开函数/常量

阅读 `_ai_parse_worker.py`，找到 LLM prompt 定义 + 返回字段映射的两处（具体位置因代码而异）。

- [ ] **Step 2: 在 LLM prompt 里新增 seniority 字段要求**

在 `_ai_parse_worker.py` 的 prompt 字符串里（原来要求 LLM 输出 name/phone/skills/work_years 的部分），加一个字段说明：

```
"seniority": "候选人职级，从 work_experience 推断，取值：初级/中级/高级/专家（无法判断输出 '中级'）"
```

具体位置按代码实情定；关键是 LLM 输出的 JSON 多一个 `seniority` 键。

- [ ] **Step 3: 在字段映射处把 seniority 写入 Resume.seniority**

找到解析 JSON 后 `resume.xxx = parsed.get(...)` 的位置，加一行：

```python
resume.seniority = (parsed.get("seniority") or "").strip() or ""
```

- [ ] **Step 4: ResumeResponse 加 seniority 字段**

Modify `app/modules/resume/schemas.py` — 在 `ResumeResponse` 里 `reject_reason` 之后加：

```python
    seniority: str = ""
```

- [ ] **Step 5: 跑现有简历测试**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/modules/resume/ -v`
Expected: 全部 pass（seniority 默认 '' 不影响既有行为）

- [ ] **Step 6: Commit**

```bash
cd D:/libz/AgenticHR
git add app/modules/resume/_ai_parse_worker.py app/modules/resume/schemas.py
git commit -m "feat(f2): infer resume seniority in AI parse worker"
```

---

## Task 20: 集成测试 — stale + upsert + audit

**Files:**
- Test: `tests/integration/test_f2_stale_detection.py`
- Test: `tests/integration/test_f2_upsert.py`
- Test: `tests/integration/test_f2_audit.py`

- [ ] **Step 1: 写 stale 测试**

Create `tests/integration/test_f2_stale_detection.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_stale_after_competency_change(db_session, client):
    cm_v1 = {"hard_skills": [], "experience": {"years_min": 0},
             "education": {}, "job_level": "中级"}
    j = Job(title="J", status="open", required_skills="",
            competency_model=cm_v1, competency_model_status="approved")
    db_session.add(j); db_session.commit()
    r = Resume(name="R", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await MatchingService(db_session).score_pair(r.id, j.id)

    # 修改能力模型
    j.competency_model = {**cm_v1, "hard_skills": [{"name": "Go", "weight": 10}]}
    db_session.commit()

    resp = client.get(f"/api/matching/results?job_id={j.id}")
    data = resp.json()
    assert data["items"][0]["stale"] is True
```

- [ ] **Step 2: 写 upsert 测试**

Create `tests/integration/test_f2_upsert.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_same_pair_single_row(db_session):
    j = Job(title="J", status="open", required_skills="",
            competency_model={"hard_skills": [], "experience": {}, "education": {}, "job_level": ""},
            competency_model_status="approved")
    db_session.add(j); db_session.commit()
    r = Resume(name="R", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    service = MatchingService(db_session)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await service.score_pair(r.id, j.id)
        await service.score_pair(r.id, j.id)
        await service.score_pair(r.id, j.id)

    count = db_session.query(MatchingResult).filter_by(
        resume_id=r.id, job_id=j.id
    ).count()
    assert count == 1
```

- [ ] **Step 3: 写 audit 测试**

Create `tests/integration/test_f2_audit.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.core.audit.models import AuditEvent
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_score_writes_audit(db_session):
    j = Job(title="J", status="open", required_skills="",
            competency_model={"hard_skills": [], "experience": {}, "education": {}, "job_level": ""},
            competency_model_status="approved")
    db_session.add(j); db_session.commit()
    r = Resume(name="R", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    before = db_session.query(AuditEvent).filter_by(
        entity_type="matching_result"
    ).count()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await MatchingService(db_session).score_pair(r.id, j.id)

    after = db_session.query(AuditEvent).filter_by(
        entity_type="matching_result"
    ).count()
    assert after == before + 1
```

- [ ] **Step 4: 跑 3 个测试**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/integration/test_f2_stale_detection.py tests/integration/test_f2_upsert.py tests/integration/test_f2_audit.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd D:/libz/AgenticHR
git add tests/integration/test_f2_stale_detection.py tests/integration/test_f2_upsert.py tests/integration/test_f2_audit.py
git commit -m "test(f2): integration tests for stale detection, upsert, audit"
```

---

## Task 21: 前端 API 客户端

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: 加 matchingApi export**

在 `frontend/src/api.js` 文件末尾（或 resumeApi 之后）加：

```javascript
export const matchingApi = {
  score(resume_id, job_id) {
    return axios.post('/api/matching/score', { resume_id, job_id }).then(r => r.data)
  },
  listByJob(job_id, { page = 1, page_size = 20, tag } = {}) {
    return axios.get('/api/matching/results', {
      params: { job_id, page, page_size, tag }
    }).then(r => r.data)
  },
  listByResume(resume_id) {
    return axios.get('/api/matching/results', { params: { resume_id } }).then(r => r.data)
  },
  recomputeJob(job_id) {
    return axios.post('/api/matching/recompute', { job_id }).then(r => r.data)
  },
  recomputeStatus(task_id) {
    return axios.get(`/api/matching/recompute/status/${task_id}`).then(r => r.data)
  },
}
```

(具体 axios 实例名以 api.js 文件实际命名为准，通常是 `axios` 或 `api`.)

- [ ] **Step 2: Commit**

```bash
cd D:/libz/AgenticHR
git add frontend/src/api.js
git commit -m "feat(f2): frontend matchingApi client"
```

---

## Task 22: 前端 Jobs.vue — "匹配候选人" Tab

**Files:**
- Modify: `frontend/src/views/Jobs.vue`

- [ ] **Step 1: 定位 Jobs.vue 现有 Tab 结构**

Run: `cd D:/libz/AgenticHR && grep -n "el-tab-pane" frontend/src/views/Jobs.vue | head -10`
Expected: 输出 Tab 位置的行号

- [ ] **Step 2: 新增一个 Tab 面板 + 列表组件**

在 Jobs.vue `<template>` 的 Tab 区域加一个新 `el-tab-pane`：

```vue
<el-tab-pane label="匹配候选人" name="matching" v-if="currentJob && currentJob.competency_model_status === 'approved'">
  <div class="matching-toolbar">
    <el-button type="primary" plain @click="recomputeMatching" :loading="matching.recomputing">重新打分</el-button>
    <el-select v-model="matching.tagFilter" placeholder="按标签筛选" clearable @change="loadMatching" style="width: 180px; margin-left: 8px">
      <el-option label="高匹配" value="高匹配" />
      <el-option label="中匹配" value="中匹配" />
      <el-option label="低匹配" value="低匹配" />
      <el-option label="硬门槛未过" value="硬门槛未过" />
    </el-select>
    <span v-if="matching.staleCount > 0" class="stale-warn">
      ⚠ {{ matching.staleCount }} 份分数基于旧能力模型
    </span>
  </div>

  <div v-loading="matching.loading">
    <el-empty v-if="!matching.items.length" description="尚无匹配结果，发布能力模型后会自动打分" />

    <div v-for="item in matching.items" :key="item.id" class="matching-row" :class="{ expanded: matching.expandedId === item.id }">
      <div class="matching-head" @click="toggleMatchingExpand(item.id)">
        <span class="m-name">{{ item.resume_name }}</span>
        <span class="m-score">{{ item.total_score.toFixed(1) }}</span>
        <div class="m-tags">
          <el-tag v-for="t in item.tags" :key="t" :type="tagType(t)" size="small">{{ t }}</el-tag>
          <el-tag v-if="item.stale" type="warning" effect="plain" size="small">⚠ 过时</el-tag>
        </div>
      </div>

      <transition name="expand">
        <div v-if="matching.expandedId === item.id" class="matching-detail">
          <div class="dim-bar" v-for="(dim, key) in dimensionList(item)" :key="key">
            <span class="dim-label">{{ dim.label }} ({{ dim.weight }}%)</span>
            <el-progress :percentage="dim.score" :color="dim.color" :stroke-width="16" />
          </div>

          <div v-if="item.hard_gate_passed === false" class="hard-gate-warn">
            🛑 硬门槛未过：缺失必须项 {{ item.missing_must_haves.join(', ') }}
          </div>

          <div class="evidence-list">
            <h4>证据片段</h4>
            <div v-for="(items, dim) in item.evidence" :key="dim">
              <div v-for="(e, i) in items" :key="i" class="evidence-item">
                <span class="ev-dim">[{{ dim }}]</span>
                <span class="ev-text">{{ e.text }}</span>
                <el-button v-if="e.source && e.offset" link size="small" @click="jumpToResume(item.resume_id, e.source, e.offset)">查看原文</el-button>
              </div>
            </div>
          </div>
        </div>
      </transition>
    </div>

    <el-pagination
      v-model:current-page="matching.page"
      :page-size="matching.pageSize"
      :total="matching.total"
      layout="total, prev, pager, next"
      @current-change="loadMatching"
      style="margin-top: 12px; justify-content: flex-end"
    />
  </div>
</el-tab-pane>
```

- [ ] **Step 3: 在 `<script setup>` 里加状态 + 方法**

```javascript
import { matchingApi, resumeApi } from '../api'
// ... 既有 imports

const matching = ref({
  loading: false,
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  tagFilter: '',
  expandedId: null,
  recomputing: false,
  staleCount: 0,
  pollTimer: null,
})

async function loadMatching() {
  if (!currentJob.value) return
  matching.value.loading = true
  try {
    const data = await matchingApi.listByJob(currentJob.value.id, {
      page: matching.value.page,
      page_size: matching.value.pageSize,
      tag: matching.value.tagFilter || undefined,
    })
    matching.value.items = data.items
    matching.value.total = data.total
    matching.value.staleCount = data.items.filter(i => i.stale).length
  } catch (e) {
    ElMessage.error('加载匹配候选人失败')
  } finally {
    matching.value.loading = false
  }
}

function toggleMatchingExpand(id) {
  matching.value.expandedId = matching.value.expandedId === id ? null : id
}

function dimensionList(item) {
  return [
    { label: '技能匹配', score: item.skill_score, weight: 35, color: scoreColor(item.skill_score) },
    { label: '工作经验', score: item.experience_score, weight: 30, color: scoreColor(item.experience_score) },
    { label: '职级对齐', score: item.seniority_score, weight: 15, color: scoreColor(item.seniority_score) },
    { label: '教育背景', score: item.education_score, weight: 10, color: scoreColor(item.education_score) },
    { label: '行业经验', score: item.industry_score, weight: 10, color: scoreColor(item.industry_score) },
  ]
}

function scoreColor(s) {
  if (s >= 80) return '#67c23a'
  if (s >= 60) return '#409eff'
  if (s >= 40) return '#e6a23c'
  return '#f56c6c'
}

function tagType(tag) {
  if (tag === '高匹配') return 'success'
  if (tag === '中匹配') return 'primary'
  if (tag === '低匹配') return 'warning'
  if (tag === '不匹配' || tag.startsWith('硬门槛') || tag.startsWith('必须项缺失-')) return 'danger'
  return 'info'
}

async function recomputeMatching() {
  if (!currentJob.value) return
  try {
    matching.value.recomputing = true
    const { task_id } = await matchingApi.recomputeJob(currentJob.value.id)
    // 轮询进度直到 running=false
    matching.value.pollTimer = setInterval(async () => {
      const s = await matchingApi.recomputeStatus(task_id)
      if (!s.running) {
        clearInterval(matching.value.pollTimer)
        matching.value.pollTimer = null
        matching.value.recomputing = false
        ElMessage.success(`打分完成：${s.completed}/${s.total}`)
        loadMatching()
      }
    }, 2000)
  } catch (e) {
    matching.value.recomputing = false
    ElMessage.error('启动打分失败')
  }
}

function jumpToResume(resumeId, source, offset) {
  // 打开简历详情页 + 传 highlight 参数
  const [start, end] = offset
  window.open(`/#/resumes/${resumeId}?highlight=${start},${end}&source=${source}`, '_blank')
}

// 在 Tab 切换 watch 里, 当 activeTab === 'matching' 时调 loadMatching()
watch(activeTab, (tab) => {
  if (tab === 'matching' && currentJob.value) loadMatching()
})

onUnmounted(() => {
  if (matching.value.pollTimer) clearInterval(matching.value.pollTimer)
})
```

（以上假设 Jobs.vue 已经有 `currentJob`、`activeTab` 等响应式变量；具体名称按现 Jobs.vue 实际代码对齐。）

- [ ] **Step 4: 加 CSS（`<style scoped>` 内）**

```css
.matching-toolbar {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 16px;
}
.stale-warn { color: #e6a23c; font-size: 13px; margin-left: 12px; }

.matching-row {
  border: 1px solid #ebeef5; border-radius: 6px;
  margin-bottom: 8px; overflow: hidden;
}
.matching-row.expanded { border-color: #409eff; }
.matching-head {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; cursor: pointer;
  transition: background 0.1s;
}
.matching-head:hover { background: #f5f7fa; }
.m-name { font-weight: 600; min-width: 80px; }
.m-score { font-size: 20px; color: #409eff; font-weight: 700; min-width: 60px; }
.m-tags { display: flex; gap: 4px; flex-wrap: wrap; }

.matching-detail { padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f0f2f5; }
.dim-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.dim-label { width: 140px; font-size: 12px; color: #606266; }
.dim-bar :deep(.el-progress) { flex: 1; }

.hard-gate-warn {
  margin-top: 10px; padding: 8px 12px;
  background: #fef0f0; color: #c45656;
  border-radius: 4px; font-size: 13px;
}
.evidence-list { margin-top: 12px; }
.evidence-list h4 { margin: 6px 0; color: #606266; font-size: 13px; }
.evidence-item { display: flex; gap: 6px; align-items: center; font-size: 13px; margin: 3px 0; }
.ev-dim { color: #909399; font-size: 11px; min-width: 70px; }
.ev-text { flex: 1; }

.expand-enter-active, .expand-leave-active { transition: all 0.2s ease-out; overflow: hidden; }
.expand-enter-from, .expand-leave-to { max-height: 0; opacity: 0; }
.expand-enter-to, .expand-leave-from { max-height: 800px; opacity: 1; }
```

- [ ] **Step 5: 手动测一次（起 dev server）**

Run: `cd D:/libz/AgenticHR/frontend && pnpm dev`
手动在浏览器打开 Jobs 页，选一个 `competency_model_status='approved'` 岗位 → 切到"匹配候选人" Tab → 验证：
- 列表展示
- 展开看 5 条维度条
- 证据片段点"查看原文"跳转
- "重新打分"能触发进度条

- [ ] **Step 6: Commit**

```bash
cd D:/libz/AgenticHR
git add frontend/src/views/Jobs.vue
git commit -m "feat(f2): Jobs.vue 匹配候选人 Tab with score bars + evidence"
```

---

## Task 23: 前端 Resumes.vue — "对接岗位分数"只读块

**Files:**
- Modify: `frontend/src/views/Resumes.vue`

- [ ] **Step 1: 在详情弹窗 `el-dialog` 里加新块**

找到 `<el-dialog v-model="showDetail" title="简历详情"...>` 里 `<el-descriptions>` 之后（关闭 `</el-descriptions>` 之后、`<template #footer>` 之前）加：

```vue
<div class="matching-block" v-if="currentMatching.length">
  <h4 style="margin: 12px 0 6px; color: #606266">对接岗位分数</h4>
  <el-table :data="currentMatching" size="small" stripe>
    <el-table-column prop="job_title" label="岗位" />
    <el-table-column label="总分" width="80">
      <template #default="{ row }">
        <span :style="{ color: scoreColor(row.total_score), fontWeight: 600 }">
          {{ row.total_score.toFixed(1) }}
        </span>
      </template>
    </el-table-column>
    <el-table-column label="标签" width="200">
      <template #default="{ row }">
        <el-tag v-for="t in row.tags" :key="t" size="small" style="margin-right: 4px">{{ t }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="120">
      <template #default="{ row }">
        <el-button size="small" link type="primary" @click="viewMatchingOnJob(row.job_id, row.resume_id)">查看 →</el-button>
      </template>
    </el-table-column>
  </el-table>
</div>
```

- [ ] **Step 2: 在 `<script setup>` 里加状态 + 加载**

```javascript
import { matchingApi } from '../api'

const currentMatching = ref([])

function scoreColor(s) {
  if (s >= 80) return '#67c23a'
  if (s >= 60) return '#409eff'
  if (s >= 40) return '#e6a23c'
  return '#f56c6c'
}

function viewMatchingOnJob(jobId, resumeId) {
  window.open(`/#/jobs/${jobId}?tab=matching&highlight_resume=${resumeId}`, '_blank')
}

// 改造 viewResume(row) 函数, 加载完简历后顺便加载匹配数据
const originalViewResume = viewResume
async function viewResume(row) {
  currentResume.value = row
  showDetail.value = true
  try {
    const data = await matchingApi.listByResume(row.id)
    currentMatching.value = data.items || []
  } catch {
    currentMatching.value = []
  }
}
```

（若 `viewResume` 已声明为 function，需改造成 async 并合并上述逻辑。）

- [ ] **Step 3: 手动测一次**

Run: `cd D:/libz/AgenticHR/frontend && pnpm dev`
在简历库点一个已打分简历的"更多详情" → 验证弹窗底部出现"对接岗位分数"表。

- [ ] **Step 4: Commit**

```bash
cd D:/libz/AgenticHR
git add frontend/src/views/Resumes.vue
git commit -m "feat(f2): Resumes.vue detail dialog shows matching scores across jobs"
```

---

## Task 24: E2E 冒烟测试

**Files:**
- Test: `tests/integration/test_f2_e2e_smoke.py`

- [ ] **Step 1: 写 E2E 测试**

Create `tests/integration/test_f2_e2e_smoke.py`:

```python
"""F2 E2E smoke: 发布能力模型 → 上传简历（mock parse）→ 见到匹配结果"""
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_e2e_smoke(db_session, client):
    # 1. 模拟已有岗位 + 已发布的能力模型
    cm = {
        "hard_skills": [
            {"name": "Python", "weight": 10, "must_have": True, "canonical_id": None, "level": "熟练"},
        ],
        "experience": {"years_min": 3, "years_max": 8, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    }
    job = Job(title="后端工程师", status="open", required_skills="",
              competency_model=cm, competency_model_status="approved")
    db_session.add(job); db_session.commit()

    # 2. 模拟简历入库（已解析完成）
    resume = Resume(
        name="张三", phone="13900000001", email="t@x.com",
        skills="Python, Go, FastAPI",
        work_experience="在某互联网公司担任后端 5 年",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
    )
    db_session.add(resume); db_session.commit()

    # 3. 手动触发 T1 (模拟解析 worker 完成调用 triggers)
    from app.modules.matching.triggers import on_resume_parsed
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)), \
         patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.95):
        await on_resume_parsed(db_session, resume.id)

    # 4. 验证 matching_results 有行
    rows = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).all()
    assert len(rows) == 1

    # 5. 经 API 读取
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["resume_name"] == "张三"
    assert item["total_score"] > 50   # sanity check: 完全匹配的简历应 > 50
    assert item["hard_gate_passed"] is True
    assert item["stale"] is False

    # 6. 验证 audit_log
    from app.core.audit.models import AuditEvent
    audits = db_session.query(AuditEvent).filter_by(entity_type="matching_result").all()
    assert len(audits) >= 1
```

- [ ] **Step 2: 验证测试通过**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/integration/test_f2_e2e_smoke.py -v`
Expected: 1 passed

- [ ] **Step 3: 跑全量验零回归**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/ --tb=short -q`
Expected: 通过数 ≥ F1 基线 + 30

- [ ] **Step 4: Commit**

```bash
cd D:/libz/AgenticHR
git add tests/integration/test_f2_e2e_smoke.py
git commit -m "test(f2): e2e smoke — approve competency → parse resume → see matching"
```

---

## Task 25: 最终验收

- [ ] **Step 1: 全量测试**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/pytest tests/ -v --tb=short`
Expected: 通过数 ≥ F1 基线 + 30，0 failures

- [ ] **Step 2: Alembic 往返验证**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/alembic downgrade -1 && .venv/Scripts/alembic upgrade head`
Expected: 两条都成功

- [ ] **Step 3: 前端 lint/type check**

Run: `cd D:/libz/AgenticHR && pnpm typecheck && pnpm test`
Expected: 无错误

- [ ] **Step 4: 启动完整服务，手动冒烟**

Run: `cd D:/libz/AgenticHR && .venv/Scripts/python -m uvicorn app.main:app --reload` (第一个终端)
Run: `cd D:/libz/AgenticHR/frontend && pnpm dev` (第二个终端)

浏览器手动走完：
1. Jobs 页创建岗位 → 粘 JD → F1 抽取 → HITL 审 → 通过发布
2. Resumes 页上传 PDF → 点 "AI 解析"
3. 回 Jobs 页该岗位 → "匹配候选人" Tab → 看到新行 + 分项条 + 证据
4. 改设置页权重 → 回 Jobs Tab → 见"⚠ 过时" → 点"重新打分" → 过时消失

- [ ] **Step 5: 更新 F2 spec status**

Modify `docs/superpowers/specs/2026-04-20-f2-resume-matching-design.md` — header 里：

```
**Status**: Implemented
```

- [ ] **Step 6: Commit**

```bash
cd D:/libz/AgenticHR
git add docs/superpowers/specs/2026-04-20-f2-resume-matching-design.md
git commit -m "docs(f2): mark spec as implemented"
```

---

## 实施后核对清单

- [ ] 所有 25 个任务 commit 完成
- [ ] F1 基线 + 30 测试通过
- [ ] Alembic upgrade/downgrade 往返 OK
- [ ] 前端手动冒烟 4 步骤走通
- [ ] spec status 更新为 Implemented
- [ ] 下游（F3/F5）准备：`/api/matching/results?resume_id=X` 可查任意简历的全部匹配，F5 调用时直接消费

---

## 回滚预案

若发现严重问题需停用 F2：

1. `app/config.py` 设 `matching_enabled = False` → 所有触发点 / API 返回 503
2. 不需要回滚 Alembic（表留着、数据留着、只是不再写入 / 读取）
3. 前端 Jobs.vue "匹配候选人" Tab 在 F2 disabled 时 503，考虑加个 error banner（Task 22 可补一个判断）

如果需要彻底回滚代码：

```bash
git revert <task-25-commit>..HEAD
alembic downgrade -1
```
