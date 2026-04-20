# F2: 简历解析 + 匹配打分 + 标签 — 设计文档

**Status**: Implemented
**Date**: 2026-04-20
**Phase**: M3 / F2
**Supersedes**: 现 `app/modules/ai_evaluation/` 的 `evaluate_single` / `evaluate_batch`（LLM-only 打分路径将被废弃）
**Parent**: [docs/superpowers/specs/2026-04-17-m3-autonomous-recruitment-design.md](./2026-04-17-m3-autonomous-recruitment-design.md)
**Depends on**: [docs/superpowers/specs/2026-04-20-f1-competency-model-design.md](./2026-04-20-f1-competency-model-design.md)（F1 能力模型产出为 F2 输入）

---

## 1. 背景与范围

### 1.1 F2 目标

把 **(一份简历, 一个岗位能力模型)** → 经规则 + 向量相似度 + 极少 LLM 调用 → 得到一份结构化 **匹配结果**：

```
总分（0-100）
├── 分项得分：技能 / 经验 / 职级 / 教育 / 行业（5 维，权重来自系统设置）
├── 证据片段（每条带简历原文 offset，支持点击跳转高亮）
├── 标签（预设集合：高匹配/中匹配/低匹配/不匹配/硬门槛未过/必须项缺失-X/学历不达标/经验不足）
├── 硬门槛判定（must_have 缺失 → 总分限制在 ≤29）
└── 过时检测哈希（competency_hash + weights_hash）
```

持久化到新表 `matching_results`，`UNIQUE(resume_id, job_id)` — 单对只保留最新。

下游消费者：HR 在岗位页按分数排序候选人 → 发起 F4 IM 初筛；F3 Boss 搜到新候选人 → 打分决定是否打招呼；F5 综合评估时把 F2 分项得分作为简历侧证据喂给 LLM。

性能要求（M3 主文档明文）：**P95 < 3s 本地 bge-m3 / < 10s 在线 API**。

### 1.2 F2 明确不做（Non-goals）

| 项 | 归属 |
|---|---|
| 简历结构化解析（PDF → 字段） | 现有 `_ai_parse_worker.py`（M2 已有）；F2 只消费 `Resume` ORM 对象 |
| 技能 level（了解/熟练/精通）比对 | 延后 V2：resume 侧没有结构化 level 字段，需 LLM 推断，V1 YAGNI |
| 985/211 `prestigious_bonus` 加分 | 延后 V2：需要学校名库，V1 YAGNI |
| 历史分数快照（多版本） | 历史追溯由 `audit_log` 承担，matching_results 单对只保留最新 |
| 自由文本标签（LLM 生成） | 违反可复现目标；预设结构化标签已覆盖筛选需求，证据片段层覆盖灵活表达 |
| IM / 面试维度综合决策 | F5 / F8 |
| bge-m3 自训练 / 双塔精调 | M4+ |

### 1.3 F2 完工定义（Done 标准）

1. `app/modules/matching/` 模块建立（`router/service/triggers/scorers/`），单测覆盖率 **≥ 85%**
2. 新表 `matching_results` 存在，5 维度分独立列 + evidence/tags JSON + competency_hash/weights_hash
3. `resumes.seniority` 字段加入；`_ai_parse_worker.py` 扩出职级推断（复用同一次 LLM 调用，零额外成本）
4. `Jobs.vue` 新增"匹配候选人" Tab 可用：分数列表 + 维度条形图 + 证据展开 + 过时徽标 + 重打分按钮
5. `Resumes.vue` 详情弹窗新增"对接岗位分数"只读块
6. 旧 `/api/ai-evaluation/evaluate` + `/evaluate/batch` 返回 410 Gone + `migrate_to` 字段
7. Alembic migration 可 `upgrade` / `downgrade` 干净往返
8. `pytest tests/` 通过数 ≥ F1 基线 + 新增（预估 +30）
9. E2E smoke 通过：新建岗位 → 发布能力模型 → 上传简历 → AI 解析 → 自动触发 F2 打分 → 岗位页"匹配候选人" Tab 看到新行

### 1.4 F2 前置依赖

- **F1 能力模型**：`jobs.competency_model` JSON + `competency_model_status='approved'`
- **既有基建**：`core/vector/service.py`（cosine_similarity）、`core/llm/`（LLM 调用）、`core/audit/`（审计）、`core/settings/router.py`（评分权重已配置）、skills 表（canonical_id + embedding）
- **既有简历解析**：`_ai_parse_worker.py` 产出的 `Resume` 对象（含 `skills`/`work_experience`/`work_years`/`education` 等字段）

---

## 2. 决策摘要

全部在 F2 brainstorm（2026-04-20）拍板：

| # | 决策项 | 选择 | 理由 |
|---|---|---|---|
| D1 | 与 `ai_evaluation` 关系 | **废弃重做** — 新开 `modules/matching`，删旧 LLM-only 打分路径 | F2 产出（分项+证据+标签+硬门槛）与旧「LLM 一把分」语义不同，留两套是技术债 |
| D2 | 打分算法风格 | **规则 + 向量为主，职级 + 证据走 LLM** | M3 主文档钦定 bge-m3 路径；可复现 + P95 可达 + 成本可控 |
| D3 | 触发时机 | **混合**：新入侧自动算，能力模型改动需手动重算（前端标"⚠ 过时"） | 平衡：简历入库 × 20 岗位可接受，能力模型改动自动雪崩爆量 |
| D4 | 标签形态 | **预设结构化集合**，阈值 80/60/40 | 可筛选 + 可复现；证据层已覆盖灵活表达 |
| D5 | 存储 | **独立新表** `matching_results`，UPSERT 单行，evidence 带 offset | (resume, job) 是 N×M，Resume 表塞不下；UNIQUE 索引自动查重；offset 支持点击高亮 |
| D6 | 硬门槛公式 | `missing_must_haves ≠ [] → total = min(raw × 0.4, 29)` | 天花板 29 保证肉眼可见低于 30 门槛；× 0.4 保留 missing 1 项 vs 2 项区分度 |
| D7 | 前端展示位置 | **岗位页为主**（Jobs.vue 新增 Tab）；简历详情只读展示 | 岗位 → 候选人是 HR 筛人最自然路径；符合 M3 主文档描述 |
| D8 | `seniority` 字段归属 | **放 Resume 表**，`_ai_parse_worker.py` 一次推断共享给所有岗位 | 每简历 1 次 LLM vs 每匹配对 1 次，成本差 N 倍 |
| D9 | 过时检测 | `competency_hash` + `weights_hash` 两个哈希比对 | 能力模型改 / 权重改都会让旧分过时，两个源都要覆盖 |
| D10 | 证据 LLM 失败处理 | **fallback 到模板** `"匹配到 {skill}（出自 {source}）"`，不阻塞打分 | LLM 是锦上添花，核心分数必须确定性产出 |
| D11 | 废弃路由处理 | **410 Gone + `migrate_to` 提示**，不静默保留 | 废弃信号要明显；debug 不留黑洞 |
| D12 | 并发保护 | `UNIQUE(resume_id, job_id)` 索引 + `db.merge()` 写赢者覆盖 | SQLite 无 `SELECT FOR UPDATE` 行锁；UNIQUE 兜底 + audit_log 保留全部调用痕迹，足够；无需引入 Redis / 分布式锁 |

---

## 3. 架构

### 3.1 模块划分

```
app/
├── core/                                    # 仅消费，零改动
│   ├── competency/schema.py                 # F1 产出的 CompetencyModel
│   ├── vector/service.py                    # cosine_similarity
│   ├── llm/                                 # 职级推断 & 证据文案
│   └── audit/                               # 审计写入
│
├── modules/
│   ├── resume/                              # 少量改动
│   │   ├── models.py                        # 扩：加 seniority VARCHAR(20)
│   │   ├── _ai_parse_worker.py              # 扩：解析 prompt 增加职级输出字段
│   │   └── schemas.py                       # 扩：ResumeResponse 增 seniority
│   │
│   ├── matching/                            # 【F2 主战场 · 全新模块】
│   │   ├── __init__.py
│   │   ├── models.py                        # MatchingResult ORM
│   │   ├── schemas.py                       # MatchingResultResponse 等 Pydantic
│   │   ├── router.py                        # REST API (prefix=/api/matching)
│   │   ├── service.py                       # MatchingService：编排 score_pair / recompute
│   │   ├── triggers.py                      # T1/T2 触发逻辑 + BackgroundTasks 接入
│   │   ├── hashing.py                       # competency_hash / weights_hash 计算
│   │   └── scorers/                         # 5 维度纯函数 + 证据生成
│   │       ├── __init__.py
│   │       ├── skill.py                     # 技能匹配（canonical_id + 向量）
│   │       ├── experience.py                # 经验年限
│   │       ├── seniority.py                 # 职级（LLM-inferred seniority 对比）
│   │       ├── education.py                 # 学历
│   │       ├── industry.py                  # 行业
│   │       ├── aggregator.py                # 加权求和 + 硬门槛 + tag 派生
│   │       └── evidence.py                  # deterministic offset + LLM 文案 fallback
│   │
│   ├── ai_evaluation/                       # 【部分废弃】
│   │   ├── service.py                       # 删除 evaluate_single / evaluate_batch
│   │   ├── router.py                        # /evaluate + /evaluate/batch 返回 410 Gone
│   │   └── schemas.py                       # 删除 EvaluationRequest/Response（留 /status）
│   │
│   └── screening/                           # 触发点接入（T2）
│       └── router.py                        # approve handler 末尾 schedule F2 batch
```

### 3.2 数据流

```
(1) 简历入库（ai_parsed=yes）────┐
                                 │
(2) 能力模型发布（approved）─────┤
                                 │
(3) HR 手动重打分 ───────────────┼──> MatchingService.score_pair(r, j)
                                 │         │
(4) HR 单对诊断 ─────────────────┘         ├─ hashing.compute_competency_hash(job)
                                           ├─ hashing.compute_weights_hash()
                                           ├─ scorers.skill.score(r, j)         → skill_score + matched + missing
                                           ├─ scorers.experience.score(r, j)    → experience_score
                                           ├─ scorers.seniority.score(r, j)     → seniority_score
                                           ├─ scorers.education.score(r, j)     → education_score
                                           ├─ scorers.industry.score(r, j)      → industry_score
                                           ├─ scorers.aggregator.aggregate(...) → total + hard_gate + tags
                                           ├─ scorers.evidence.generate(...)    → evidence JSON (deterministic + LLM)
                                           ├─ db.merge(MatchingResult(...))     → UPSERT (UNIQUE 索引兜底)
                                           └─ audit_log.insert(entity='matching_result', ...)
```

---

## 4. 数据模型

### 4.1 新表 `matching_results`

```sql
CREATE TABLE matching_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resume_id INTEGER NOT NULL,
  job_id INTEGER NOT NULL,

  -- 总分（0-100 浮点）
  total_score REAL NOT NULL,

  -- 5 维度分（独立列，便于 SQL 排序/筛选）
  skill_score REAL NOT NULL,
  experience_score REAL NOT NULL,
  seniority_score REAL NOT NULL,
  education_score REAL NOT NULL,
  industry_score REAL NOT NULL,

  -- 硬门槛
  hard_gate_passed INTEGER NOT NULL DEFAULT 1,     -- SQLite 无 BOOLEAN，用 INTEGER 0/1
  missing_must_haves TEXT NOT NULL DEFAULT '[]',   -- JSON: ["Python", "Kubernetes"]

  -- 证据（JSON，按维度分组）
  evidence TEXT NOT NULL DEFAULT '{}',
  -- 结构：
  -- {
  --   "skill":      [{"text": "匹配到 Python", "source": "project_experience", "offset": [45, 72]}, ...],
  --   "experience": [{"text": "工作年限 5 年，要求 3-8 年", "source": "work_years", "offset": null}],
  --   "seniority":  [...],
  --   "education":  [...],
  --   "industry":   [...]
  -- }

  -- 标签
  tags TEXT NOT NULL DEFAULT '[]',                 -- JSON: ["中匹配", "必须项缺失-Python"]

  -- 过时检测
  competency_hash TEXT NOT NULL,                   -- SHA1 of canonical JSON of job.competency_model
  weights_hash TEXT NOT NULL,                      -- SHA1 of canonical JSON of ScoringWeights

  scored_at DATETIME NOT NULL,

  UNIQUE(resume_id, job_id)
);

CREATE INDEX idx_mr_job_score ON matching_results(job_id, total_score DESC);
CREATE INDEX idx_mr_resume ON matching_results(resume_id);
```

**设计要点**：
- 5 维度独立列：将来可能"按经验维度排序"、"列出技能分 < 50 的候选人"这类 SQL 查询，JSON blob 做不到
- `UNIQUE(resume_id, job_id)`：对应 `db.merge()` 语义 UPSERT；重打分只覆盖不累积
- 双 hash：`competency_hash` 独立能覆盖能力模型修改；`weights_hash` 独立能覆盖 HR 在设置页改权重；前端"⚠ 过时"判定：`stale = result.competency_hash != current_competency_hash or result.weights_hash != current_weights_hash`
- `scored_at` 只记最新；历史查 `audit_log`

### 4.2 Resume 表扩字段

```sql
ALTER TABLE resumes ADD COLUMN seniority VARCHAR(20) DEFAULT '' NOT NULL;
-- 值域: '初级' / '中级' / '高级' / '专家' / ''（空串 = 未推断）
```

`_ai_parse_worker.py` 的 LLM 简历解析 prompt 追加一个输出字段 `seniority`：

```json
{
  "name": "...",
  "work_years": 5,
  "skills": "Python, FastAPI, ...",
  "seniority": "高级"   // ← 新增，取值："初级"/"中级"/"高级"/"专家"
  ...
}
```

零额外 LLM 调用（搭既有简历解析的便车）。

### 4.3 `ScoringWeights` 无需改动

`core/settings/router.py` 现有 `skill_match/experience/seniority/education/industry` 5 项，与 F2 5 维度一一对齐。默认 35/30/15/10/10。

### 4.4 Alembic migration

文件：`app/migrations/versions/20260420_add_f2_matching.py`

```python
def upgrade():
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

    op.add_column('resumes',
        sa.Column('seniority', sa.String(20), nullable=False, server_default=''))


def downgrade():
    op.drop_index('idx_mr_resume', 'matching_results')
    op.drop_index('idx_mr_job_score', 'matching_results')
    op.drop_table('matching_results')
    op.drop_column('resumes', 'seniority')
```

---

## 5. 打分算法

### 5.1 技能匹配（权重 35%）

两段式匹配，对每个 `competency.hard_skills[i]`：

```python
# Phase 1: canonical_id 精确匹配（零成本）
if hard_skill.canonical_id:
    if any(rs.canonical_id == hard_skill.canonical_id for rs in resume_skills_canonicalized):
        coverage[i] = 1.0
        continue

# Phase 2: bge-m3 向量相似度补充
hs_vec = embed(hard_skill.name)
sim = max((cosine_similarity(hs_vec, embed(rs.name)) for rs in resume_skills), default=0.0)

if sim >= 0.75:
    coverage[i] = sim                     # 0.75-1.0 线性传递
elif sim >= 0.60:
    coverage[i] = sim * 0.5               # 边缘匹配打折（避免假阳性）
else:
    coverage[i] = 0.0
    if hard_skill.must_have:
        missing_must_haves.append(hard_skill.name)

# 加权聚合
skill_score = sum(hs[i].weight * coverage[i] for i in ...) / sum(hs[i].weight for i in ...) * 100
```

**阈值说明**：
- `0.75` 是 bge-m3 在中文技能词上的经验"同义/近义"门槛（"Python 开发" vs "Python" ≈ 0.88，"Python" vs "JavaScript" ≈ 0.55）
- `0.60` 以下不计分（避免"Java" vs "JavaScript" 这类假阳性 ≈ 0.58 被误当匹配）
- 首次实现后需用真实数据校准，写入 `tests/fixtures/skill_similarity_golden.json` 回归

**技能 level（了解/熟练/精通）V1 不比对**：resume 侧没有结构化 level，从 work_experience 推断需 LLM，YAGNI 延后 V2。

### 5.2 工作经验（权重 30%）

```python
years = resume.work_years
ymin = competency.experience.years_min
ymax = competency.experience.years_max or (ymin + 10)   # 上限未设 → ymin + 10

if ymin <= years <= ymax:
    experience_score = 100.0
elif years < ymin:
    experience_score = (years / ymin) * 100.0 if ymin > 0 else 100.0
else:
    # 过度资深：线性降，最低保 60
    experience_score = max(60.0, 100.0 - (years - ymax) * 10)
```

### 5.3 职级（权重 15%）

```python
LEVEL_MAP = {
    "初级|junior|实习": 1,
    "中级|mid|regular": 2,
    "高级|senior": 3,
    "专家|lead|主管|总监|staff|principal": 4,
}

def match_ordinal(text: str) -> int:
    """Free-text job_level/seniority → 1-4 ordinal"""
    text_lower = (text or "").lower()
    for pattern, ord_ in LEVEL_MAP.items():
        if any(kw in text_lower for kw in pattern.split("|")):
            return ord_
    return 2   # 默认中级

required = match_ordinal(competency.job_level)
candidate = match_ordinal(resume.seniority)   # 上游 LLM 已推断

diff = candidate - required
if diff >= 0:    seniority_score = 100.0   # 够或过
elif diff == -1: seniority_score = 60.0
else:            seniority_score = 20.0
```

**简历职级未推断（`seniority=''`）**：`match_ordinal("")` 返回 2（默认中级），算"按 work_years 自然推断"fallback 即可，不触发 LLM 补推断（避免打分时多次 LLM 调用）。

### 5.4 学历（权重 10%）

```python
EDU_ORD = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}

r = EDU_ORD.get(resume.education, 0)
m = EDU_ORD.get(competency.education.min_level, 2)

if r >= m:
    education_score = 100.0
else:
    education_score = max(0.0, 100.0 - (m - r) * 40)

# V1 不实现 prestigious_bonus (985/211/C9 学校名库)，YAGNI 延后 V2
```

### 5.5 行业（权重 10%）

```python
industries = competency.experience.industries

if not industries:
    industry_score = 100.0   # 无要求 → 满分
else:
    hits = 0
    for industry in industries:
        # Phase 1: 关键词包含匹配
        if industry.lower() in resume.work_experience.lower():
            hits += 1
            continue
        # Phase 2: 向量相似度（对未命中的）
        ind_vec = embed(industry)
        exp_vec = embed(resume.work_experience[:500])   # 截前 500 字避免长文本
        if cosine_similarity(ind_vec, exp_vec) >= 0.70:
            hits += 1
    industry_score = (hits / len(industries)) * 100.0
```

### 5.6 聚合 + 硬门槛 + 标签

```python
weights = load_scoring_weights()   # from core/settings/router
assert weights.total() == 100

raw_total = (
    skill_score      * weights.skill_match +
    experience_score * weights.experience +
    seniority_score  * weights.seniority +
    education_score  * weights.education +
    industry_score   * weights.industry
) / 100.0

# 硬门槛
if missing_must_haves:
    total_score = min(raw_total * 0.4, 29.0)
    hard_gate_passed = False
else:
    total_score = raw_total
    hard_gate_passed = True

# 标签派生
tags = []
if not hard_gate_passed:
    tags.append("硬门槛未过")
    tags.extend(f"必须项缺失-{s}" for s in missing_must_haves[:3])   # 最多 3 个避免刷屏
else:
    if   total_score >= 80: tags.append("高匹配")
    elif total_score >= 60: tags.append("中匹配")
    elif total_score >= 40: tags.append("低匹配")
    else:                   tags.append("不匹配")

if education_score < 50:  tags.append("学历不达标")
if experience_score < 50: tags.append("经验不足")
```

### 5.7 证据片段

**两层生成**：

**Deterministic 层（永远产出）**：

```python
# 技能维度：每个匹配到的技能，regex 找首次出现记 offset
for skill_name, source_field in iter_matched_skills(...):
    m = re.search(re.escape(skill_name), getattr(resume, source_field), re.IGNORECASE)
    if m:
        evidence["skill"].append({
            "text": f"匹配到 {skill_name}",
            "source": source_field,            # "skills" / "work_experience" / "project_experience"
            "offset": [m.start(), m.end()],
        })

# 经验/学历：结构化字段引用，offset=null
evidence["experience"].append({
    "text": f"工作年限 {resume.work_years} 年，要求 {ymin}-{ymax} 年",
    "source": "work_years",
    "offset": None,
})

# 行业：关键词命中位置
for industry in matched_industries:
    m = re.search(re.escape(industry), resume.work_experience, re.IGNORECASE)
    if m:
        evidence["industry"].append({
            "text": f"行业匹配：{industry}",
            "source": "work_experience",
            "offset": [m.start(), m.end()],
        })
```

**LLM 层（一次打分一次调用，可关）**：

```python
# 单次 LLM 调用，输入 5 维分数 + 命中/未命中列表 + 简历摘要
# 输出：5 条自然语言证据，每条 ≤ 30 字
try:
    llm_evidence = await llm.generate_evidence(...)
    # 把 LLM 输出的 text 覆盖到 deterministic 的 text（保留 source + offset）
    for dim, snippets in llm_evidence.items():
        for i, text in enumerate(snippets):
            if i < len(evidence[dim]):
                evidence[dim][i]["text"] = text
except Exception:
    pass   # LLM 失败不阻塞；deterministic 模板已产出
```

**开关**：`app/config.py` 加 `matching_evidence_llm_enabled: bool = True`（见 §11）。默认开，性能问题或 LLM 不可用时 HR 可关，降级到纯 deterministic 证据。

### 5.8 性能预算

| 步骤 | 耗时预估 |
|---|---|
| 读 resume + competency | < 10ms |
| 技能 canonical_id 精确匹配 | < 5ms |
| 技能向量相似度（~20 skill × 20 resume skill，本地 bge-m3） | ~300ms |
| 经验/职级/学历 纯规则 | < 30ms |
| 行业向量匹配（~5 industry） | ~100ms |
| 聚合 + 标签 + deterministic 证据 | < 10ms |
| LLM 证据调用（可并行 batch） | ~1.5s |
| UPSERT matching_results + audit_log | < 50ms |
| **总计** | **~2s（本地）/ ~5s（API）** ✅ 达标 |

---

## 6. 触发策略

| ID | 触发点 | 触发来源 | 打分范围 | 执行方式 |
|---|---|---|---|---|
| **T1** | 简历入库（`ai_parsed` 置为 `yes`） | `_ai_parse_worker.py` 解析成功 callback | 所有 `jobs.status='open'` + `competency_model_status='approved'` 的岗位 | FastAPI `BackgroundTasks`，不阻塞解析响应 |
| **T2** | 能力模型发布（`competency_model_status` 置为 `approved`） | `screening/router.py` 的 approve handler | 过去 90 天（`resumes.created_at >= now - 90d`）入库的 `ai_parsed='yes'` 简历 | `BackgroundTasks`，一条条跑 |
| **T3** | HR 手动"重新打分"（岗位页按钮） | `POST /api/matching/recompute {job_id}` | 该岗位 × 全库 `ai_parsed='yes'` 简历 | 异步任务，返回 `{task_id}`；前端轮询 `/recompute/status/{task_id}` |
| **T4** | HR 手动"单对打分"（诊断用） | `POST /api/matching/score {resume_id, job_id}` | 单对 | 同步，2-5s 返回完整结果 |

**并发保护**：SQLite 无 `SELECT ... FOR UPDATE`，改用 `db.merge()` + `UNIQUE(resume_id, job_id)` 索引兜底：并发两次打同对时最终仅落一行（后者覆盖前者），每次调用都在 `audit_log` 留痕可追溯。

**进度接入**：T1 / T2 沿用既有 `_ai_parse_worker` 的进度广播机制（前端 `Resumes.vue` 已在轮询），避免重复造轮子。T3 独立新接口 `/api/matching/recompute/status/{task_id}`。

---

## 7. API Surface

### 7.1 新增（`modules/matching/router.py`，prefix `/api/matching`）

```
GET    /api/matching/results
       query: job_id=X | resume_id=X, page=1, page_size=20, tag=高匹配
       → {total, items: [MatchingResultResponse]}
       按 total_score DESC 分页，支持按 tag 筛选；前端岗位 Tab / 简历详情共用

POST   /api/matching/score
       body: {"resume_id": 1, "job_id": 2}
       → MatchingResultResponse
       单对同步打分（2-5s），用于 HR 诊断

POST   /api/matching/recompute
       body: {"job_id": 2} OR {"resume_id": 1}
       → {"task_id": "...", "total": 420}
       批量异步打分

GET    /api/matching/recompute/status/{task_id}
       → {total, completed, failed, running, current}
```

### 7.2 响应 schema

```python
class EvidenceItem(BaseModel):
    text: str
    source: str              # "skills" / "work_experience" / "project_experience" / "work_years" / ...
    offset: list[int] | None = None

class MatchingResultResponse(BaseModel):
    id: int
    resume_id: int
    resume_name: str         # eager-loaded from Resume
    job_id: int
    job_title: str           # eager-loaded from Job

    total_score: float
    skill_score: float
    experience_score: float
    seniority_score: float
    education_score: float
    industry_score: float

    hard_gate_passed: bool
    missing_must_haves: list[str]

    evidence: dict[str, list[EvidenceItem]]   # 按维度分组
    tags: list[str]

    stale: bool                                # 服务端对比当前 hash 算出
    scored_at: datetime
```

### 7.3 废弃（`modules/ai_evaluation/router.py`）

```
POST /api/ai-evaluation/evaluate          → 410 Gone, body={"detail": "...", "migrate_to": "/api/matching/score"}
POST /api/ai-evaluation/evaluate/batch    → 410 Gone, body={"detail": "...", "migrate_to": "/api/matching/recompute"}
GET  /api/ai-evaluation/status            → 保留（LLM 健康检查，F5 会用）
```

`service.py` 的 `evaluate_single` / `evaluate_batch` 函数整体删除。前端调用方同步改（见 §8）。

---

## 8. 前端改动

### 8.1 `Jobs.vue` — 新增"匹配候选人" Tab（主战场）

在 Jobs 详情页原有 Tab（基本信息 / 能力模型 / 候选人）旁插入 "匹配候选人" Tab：

```
┌ Tab: 基本信息 │ 能力模型 │ 匹配候选人 ←新 │
│                                               │
│  工具栏: [重新打分 ↻] [筛选标签 ▼] [搜姓名 🔍]           │
│  过时提示: ⚠ 3 份分数基于旧能力模型 [全部重算]          │
│                                                         │
│  ┌ 张三 · 85 分 · 高匹配 · ▾ ────────────────────────┐ │
│  │  技能匹配 ████████░ 80%  (权重 35%)                │ │
│  │  工作经验 ██████░░░ 60%  (权重 30%)                │ │
│  │  职级对齐 ███████░░ 70%  (权重 15%)                │ │
│  │  教育背景 ██████████ 100% (权重 10%)               │ │
│  │  行业经验 █████░░░░░ 50%  (权重 10%)               │ │
│  │  证据:                                             │ │
│  │    ✓ 匹配到 Python（项目经历 L45-72）              │ │
│  │    ✓ 工作年限 5 年，要求 3-8 年                     │ │
│  │    ⊝ 行业不完全对齐：教育 vs 互联网                 │ │
│  │  [查看简历详情] [发起 IM 初筛（F4）]                │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌ 李四 · 28 分 · 硬门槛未过 · 必须项缺失-Python · ▸ ┐ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**交互细节**：
- 紧凑行：姓名 · 总分 · 标签 chips · 过时徽标（若 stale）· 展开箭头 — 与 `Resumes.vue` 的展开风格对齐
- 展开后：5 维度水平进度条（颜色：<40 红 / 40-60 橙 / 60-80 蓝 / ≥80 绿），hover 显示权重
- 证据片段：每条可点击，跳转到对应简历页 + 高亮 offset 范围（简历原文查看页需支持 `?highlight=start,end` URL 参数）
- 过时徽标：单行的 `stale=true` 显示 `⚠ 过时`；顶部"重新打分"是整岗位批量重算
- "重新打分"按钮：点击 → `POST /recompute` → 出现进度条组件（复用 `_ai_parse_worker` 的 UI 模式）

### 8.2 `Resumes.vue` — 最小改动

简历详情弹窗里新增"匹配岗位"只读块：

```
┌ 匹配岗位 ────────────────────────────┐
│ 后端开发（Job#2）│ 85 · 高匹配 │ [详情 →] │
│ 全栈工程师（Job#5）│ 62 · 中匹配 │ [详情 →] │
│ DevOps（Job#8）│ 28 · 硬门槛未过 │ [详情 →] │
└──────────────────────────────────────┘
```

- 数据源：`GET /api/matching/results?resume_id=X`
- 每行点击 [详情] → 跳 `Jobs.vue` 对应岗位 Tab + 自动展开该候选人行
- 主列表页**不加**"匹配分"列（D7 决定保持简历库纯净）

### 8.3 旧"AI 解析"按钮处理

`Resumes.vue` 顶部的 "AI 解析" 按钮（`aiParseSingle` / `aiParseAll`）**保留不变** — 它调用的是 `_ai_parse_worker`（简历结构化解析），不是 `ai_evaluation/evaluate`。

调用 `ai_evaluation/evaluate` 的前端点（如果有）需要定位并改调 `/api/matching/score`。实施期 Grep 验证：

```bash
rg "/api/ai-evaluation/evaluate" frontend/
```

### 8.4 `Settings.vue` — 无需改动

评分权重页已就位（F1 完成时建立）。F2 消费同一份 `ScoringWeights`，权重的改动自动让旧分数 `stale=true`。

---

## 9. 测试策略

对齐 `AgenticHR/CLAUDE.md` 的 "TDD 强制 + 先写失败测试" 约束。

### 9.1 单元测试（`tests/modules/matching/`）

| 文件 | 覆盖 case |
|---|---|
| `test_scorer_skill.py` | canonical_id 精确匹配 / 向量阈值 0.75-1.0 / 边缘 0.60-0.75 打折 / < 0.60 不计分 / `must_have` 缺失被记录 / 多技能加权聚合 / 空技能列表 |
| `test_scorer_experience.py` | 满足范围 / 不足线性降 / 过度资深线性降到 60 底 / `years_min=0` 边界 / `years_max=None` 默认 +10 |
| `test_scorer_seniority.py` | LEVEL_MAP 关键词命中 / free text fallback 到默认中级 / resume.seniority 空串 / diff 0/-1/-2+ 三档 |
| `test_scorer_education.py` | 学历档差 0/1/2/3 / EDU_ORD unknown 返回 0 / min_level 默认本科 |
| `test_scorer_industry.py` | 空要求 = 100 / 关键词包含命中 / 向量 fallback 阈值 0.70 / 多行业命中比例 |
| `test_aggregator.py` | 加权求和 / `missing_must_haves=[]` 不触发硬门槛 / 有 missing → `total = min(raw×0.4, 29)` / hard_gate_passed 字段 |
| `test_tags.py` | 阈值边界 (79/80/60/40) / 硬门槛优先 / must_have 最多 3 个 / 学历+经验分低时叠加 tag |
| `test_evidence_deterministic.py` | offset 正确 / 多字段 source 正确 / 未匹配技能不出现在 evidence |
| `test_evidence_llm_fallback.py` | LLM mock 抛异常 → deterministic 模板保留 / LLM 成功 → text 被覆盖但 source/offset 不变 |
| `test_hashing.py` | 同内容 JSON 排序后 hash 稳定 / 内容修改 hash 变化 / ScoringWeights 改动 hash 变化 |

### 9.2 集成测试（`tests/integration/`）

| 文件 | 覆盖 |
|---|---|
| `test_f2_trigger_resume_ingest.py` | 简历 `ai_parsed=yes` → BackgroundTasks 触发 → `matching_results` 行数 = open 岗位数 |
| `test_f2_trigger_competency_approve.py` | 能力模型 approve → 过去 90 天简历打分；超 90 天简历不打分 |
| `test_f2_recompute_job.py` | `POST /recompute {job_id}` → task_id 返回 → status 流转 pending→running→done |
| `test_f2_stale_detection.py` | 能力模型改后查询 results → 服务端 `stale=true` / 权重改后同理 |
| `test_f2_upsert.py` | 同对打两次 → 只有一行 / `scored_at` 更新 / 旧 `total_score` 被覆盖 |
| `test_f2_concurrency.py` | 并发两次打同对 → UNIQUE 索引兜底，最终一行；audit_log 留两条 |
| `test_f2_audit.py` | 每次打分 → audit_log 多一条 `entity_type='matching_result'`、`output_payload.total` 存在 |
| `test_deprecated_evaluate.py` | POST /ai-evaluation/evaluate → 410 + `migrate_to="/api/matching/score"` |
| `test_e2e_smoke.py` | 新建岗位 → 粘 JD → F1 抽取 → HITL approve → 上传 PDF → AI 解析 → F2 自动打分 → Jobs.vue Tab 见新行 |

### 9.3 性能测试

`tests/performance/test_f2_latency.py`：

- 单对打分 P95 < 3s（本地 bge-m3）/ < 10s（API），固定 resume + competency fixture
- 批量 100 对打分 <= 5 分钟

### 9.4 基线

F1 完工时 `pytest tests/` 通过数 N（预计 ≥ 53）。F2 后应 ≥ N + 30。实施期每阶段跑全量确认不回归。

---

## 10. 审计

每次 `MatchingService.score_pair(r, j)` 成功后写一条 `audit_log`：

```python
audit_log.insert({
    "entity_type": "matching_result",
    "entity_id": matching_result.id,
    "action": "score",
    "actor_type": "system" if triggered_by in ("T1", "T2") else "user",
    "actor_id": current_user.id if triggered_by in ("T3", "T4") else None,
    "input_payload": {
        "resume_id": r.id,
        "job_id": j.id,
        "trigger": triggered_by,                   # T1/T2/T3/T4
        "competency_hash": competency_hash,
        "weights_hash": weights_hash,
    },
    "output_payload": {
        "total_score": total,
        "dim_scores": {skill, experience, seniority, education, industry},
        "tags": [...],
        "hard_gate_passed": bool,
        "missing_must_haves": [...],
    },
    "created_at": now(),
})
```

审计的增量只是 `entity_type='matching_result'` 一种新值，`core/audit/` 无需改。

---

## 11. 配置项（`app/config.py`）

新增三个 settings：

```python
class Settings:
    # F2 开关
    matching_enabled: bool = True                          # 总开关
    matching_evidence_llm_enabled: bool = True             # 证据 LLM 生成开关
    matching_trigger_days_back: int = 90                   # T2 新岗位触发时回溯简历的天数
    matching_skill_sim_exact: float = 0.75                 # 技能精确匹配阈值
    matching_skill_sim_edge: float = 0.60                  # 技能边缘匹配阈值
    matching_industry_sim: float = 0.70                    # 行业向量匹配阈值
```

---

## 12. 部署 / 灰度

F2 无外部依赖新增（bge-m3 / LLM 已在 M3 主文档方案内）。部署步骤：

1. 跑 Alembic migration：`alembic upgrade head`
2. 重启后端；触发一次 E2E smoke 验证
3. HR 在岗位页点"重新打分"对主力岗位全量打一次；其后新简历自动触发 T1

**回滚预案**：`matching_enabled=False` 关总开关 → 触发点都跳过、API 返回 503 `feature_disabled`，保留 `ai_evaluation/status` 健康检查路由让 F5 准备期不报错。

---

## 13. 未决 / 延后事项

| 项 | 何时做 |
|---|---|
| 技能 level 比对（了解/熟练/精通） | V2（需要 resume 侧推断 level，LLM 成本） |
| `prestigious_bonus` 985/211 加分 | V2（需要学校名库维护） |
| 历史分数快照 / 趋势图 | M5+（`audit_log` 已能追溯） |
| 能力模型 / 权重改动时自动重算 | 保留 D3 决策：显式触发，不自动雪崩 |
| bge-m3 HR 领域精调（`bge-m3-hr-zh`） | M4+（M3 文档列为长期目标） |
| 向量缓存 / 持久化 embedding | V2 性能优化（V1 每次打分现算，可接受） |

---

## 14. 变更日志

| 日期 | 变更 | 作者 |
|---|---|---|
| 2026-04-20 | 首稿（基于 F2 brainstorm 决策 D1-D12） | Claude Opus 4.7 |
