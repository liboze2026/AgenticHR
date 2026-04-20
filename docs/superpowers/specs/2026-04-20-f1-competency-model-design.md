# F1: 能力模型抽取 — 设计文档

**Status**: Draft
**Date**: 2026-04-20
**Phase**: M3 / F1
**Supersedes**: N/A (M3 首个 F)
**Parent**: [docs/superpowers/specs/2026-04-17-m3-autonomous-recruitment-design.md](./2026-04-17-m3-autonomous-recruitment-design.md)

---

## 1. 背景与范围

### 1.1 F1 目标

把 **JD 文本** → 经 LLM 结构化抽取 + 技能库归一化 → 得到一份 `competency_model` JSON（存于 `jobs.competency_model` 列），HR 审核通过后作为 F2–F8 所有下游决策（简历匹配、IM 初筛、面试评估、最终决策）的**唯一依据**。

### 1.2 F1 明确不做（Non-goals）

| 项 | 归属 |
|---|---|
| 简历侧匹配打分 + 证据片段抽取 | F2 |
| bge-m3 本地 embedding | M4（生产推在线 API，本地为可选 fallback） |
| 能力模型版本 diff / 历史对比 UI | M5+（F1 只保留最新版 + 审计日志留痕） |
| 团队二审 / 多 reviewer 流程 | M4 多租户化 |
| 能力模型自动发布（无 HITL 路径） | 违反 PIPL §24 红线，永不做 |

### 1.3 F1 完工定义（Done 标准）

1. `app/core/{llm,competency,vector,hitl,audit}/` 五个包建立，单测覆盖率 **≥ 85%**
2. `screening` 模块扩出 LLM 抽取 service，能把 JD 转为能力模型
3. 新表 `skills` / `hitl_tasks` / `audit_events` 存在，含 WORM 触发器
4. `jobs` 表扩 3 列：`jd_text` / `competency_model` / `competency_model_status`
5. `Jobs.vue` 能力模型 Tab 可用，6 折叠卡片 + JD 抽取 + 两键模型（保存草稿 / 通过发布）
6. `HitlQueue.vue` + `SkillLibrary.vue` 两个新页可用
7. 扁平字段筛选（M2 行为）**零回归**：`pytest tests/` 通过数 ≥ 53（现基线）
8. Alembic migration 可 `upgrade` / `downgrade` 干净往返
9. E2E smoke 通过：创建岗位 → 粘 JD → 抽取 → HITL 审 → approve → 跑硬筛 → 结果正确

### 1.4 F1 前置依赖

- **M3-kickoff-K0 + K1**：Alembic 引入 + baseline migration + `alembic stamp head` 对齐现数据库。F1 的所有 schema 变更走 Alembic，不再用 `create_tables()`。

---

## 2. 决策摘要

全部在 F1 brainstorm（2026-04-20）拍板：

| # | 决策项 | 选择 | 理由 |
|---|---|---|---|
| D1 | Alembic 引入时机 | **M3-kickoff 独立任务，F1 前置** | 风险隔离：F1 本身已有 LLM + 归一化 + HITL + 审计四件复杂事 |
| D2 | 扁平字段（`education_min` / `required_skills` 等）退场策略 | **双写过渡**：写 competency_model 时同时回填扁平字段；读走 competency_model；M3 末独立 migration 清理 | M2 回归兜底 + 老数据懒迁移 + F1 scope 聚焦 |
| D3 | HITL 切入点 1（能力模型本身） | **阻塞**：必审才能发布 | 所有下游消费的唯一依据，PIPL §24 红线 |
| D4 | HITL 切入点 2（新技能入库） | **非阻塞**：后台写入 skills 表 `pending_classification=1`，在 `SkillLibrary.vue` 事后批量归类 | 避免 HR "为建一个岗位等技能归类" 的体验 |
| D5 | HITL 切入点 3（HR 手改权重） | **无 HITL**：HR 自己即 reviewer | F1 单 HR / 单团队场景；多 reviewer 是 M4 事 |
| D6 | LLM 抽取失败 | 重试 3 次（指数退避 1s/3s/9s）→ 降级到**扁平字段手填表单** | HR 永远有出路，不被堵死 |
| D7 | 前端编辑器形态 | **Tab in Jobs.vue**，6 个折叠卡片（硬技能/软技能/经验/学历/加分淘汰/考察维度） | 复用现页面、无新路由、scope 最小 |
| D8 | JD 原文存储 | `jobs.jd_text TEXT DEFAULT ''` 新列 | 重抽取需要原文；审计需要原文 hash |
| D9 | 能力模型版本管理 | **只保留最新**，历史由 audit_events + data/audit/*.json 承担 | F1 不做 diff UI |
| D10 | Embedding 来源 | 在线 API（沿用 `AI_BASE_URL`，调用 `/embeddings` 端点，兼容智谱/通义/DeepSeek 等 OpenAI 兼容接口） | 本地 bge-m3 (~2GB) 部署压力，生产推 API 优先 |

---

## 3. 数据模型

### 3.1 `jobs` 表扩展（3 个新列）

```sql
ALTER TABLE jobs ADD COLUMN jd_text TEXT DEFAULT '';
ALTER TABLE jobs ADD COLUMN competency_model JSON DEFAULT NULL;
ALTER TABLE jobs ADD COLUMN competency_model_status TEXT DEFAULT 'none';
-- 取值: none | draft | approved | rejected
```

- `jd_text`：JD 原文，HR 粘贴；`''` = 老岗位未填
- `competency_model`：结构化能力模型（schema 见 §3.6），`NULL` = 尚未生成
- `competency_model_status`：四态机
  - `none`：从未抽取
  - `draft`：LLM 抽完 + 等 HITL
  - `approved`：HITL 通过，F2+ 可消费
  - `rejected`：HITL 驳回，HR 决定是否重抽

**扁平字段保留**：`education_min` / `work_years_min/max` / `salary_min/max` / `required_skills` / `soft_requirements` / `greeting_templates` **全部保留**，F1 双写（由 `approve` 触发回填），M3 末独立 migration 统一删除。

### 3.2 `skills` 表（新建）

```sql
CREATE TABLE skills (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name         TEXT UNIQUE NOT NULL,
  aliases                JSON DEFAULT '[]',
  category               TEXT DEFAULT 'uncategorized',
  embedding              BLOB,
  source                 TEXT NOT NULL,                 -- seed | llm_extracted | seed_manual
  pending_classification BOOLEAN DEFAULT 0,
  usage_count            INTEGER DEFAULT 0,
  created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_skills_category ON skills(category);
CREATE INDEX idx_skills_pending
  ON skills(pending_classification)
  WHERE pending_classification = 1;
```

- `embedding`：`np.array(vec, dtype=np.float32).tobytes()`，维度以 embedding 模型实际输出为准（智谱 `embedding-2` = 1024 维 × 4 字节 = 4096 字节；`embedding-3` = 2048 维 = 8192 字节）。列不约束长度，但同一批种子必须维度一致
- `source=seed` 不可 DELETE；`source=llm_extracted` 且 `usage_count=0` 可删
- 允许 `embedding=NULL`（AI 未配置环境下 seed 先落，首次被归一化时懒加载）

### 3.3 `hitl_tasks` 表（新建）

```sql
CREATE TABLE hitl_tasks (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  f_stage        TEXT NOT NULL,
  entity_type    TEXT NOT NULL,                 -- job | skill
  entity_id      INTEGER NOT NULL,
  payload        JSON NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | edited
  edited_payload JSON,
  reviewer_id    INTEGER,
  reviewed_at    DATETIME,
  note           TEXT,
  created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_hitl_status ON hitl_tasks(status);
CREATE INDEX idx_hitl_stage ON hitl_tasks(f_stage, status);
```

**F1 使用的 `f_stage` 值**：
- `F1_competency_review`：阻塞型，`entity_type='job'`
- `F1_skill_classification`：非阻塞型，`entity_type='skill'`

**多态关联**：`(entity_type, entity_id)` 不加 FK — 保持审计中立性，被审实体删了 HITL 记录也在。

### 3.4 `audit_events` 表（新建，WORM）

```sql
CREATE TABLE audit_events (
  event_id        TEXT PRIMARY KEY,              -- UUID v4
  f_stage         TEXT NOT NULL,
  action          TEXT NOT NULL,
  entity_type     TEXT NOT NULL,
  entity_id       INTEGER,
  input_hash      TEXT,                          -- SHA256(input payload)
  output_hash     TEXT,
  prompt_version  TEXT,
  model_name      TEXT,
  model_version   TEXT,
  reviewer_id     INTEGER,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  retention_until DATETIME                       -- created_at + 3 年
);

CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
  FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'WORM'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
  FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'WORM'); END;

CREATE INDEX idx_audit_entity ON audit_events(entity_type, entity_id);
CREATE INDEX idx_audit_stage  ON audit_events(f_stage, created_at);
```

- **WORM 强约束**：DB 级禁 `UPDATE/DELETE`。单元测试专项覆盖（见 §8.1）。
- **大 payload 外置**：原始 input/output 写 `data/audit/{event_id}.json`。M5 迁 MinIO。
- **保留期**：默认 `retention_until = created_at + 3 年`。清理逻辑 M5+ 做，F1 只写不清。

### 3.5 F1 审计记点清单

| action | 触发 | entity_type | 备注 |
|---|---|---|---|
| `extract` | LLM 调用（无论成败，记耗时和结果哈希） | job | |
| `extract_fail` | 3 次重试全败 | job | |
| `normalize` | 每个技能归一化决定 | skill | `note` 字段标记 `reuse` 或 `new` |
| `hitl_create` | 创建阻塞/非阻塞任务 | job 或 skill | |
| `hitl_approve` / `hitl_reject` / `hitl_edit` | HR 操作 | job 或 skill | 阻塞任务 approve 时同时 `publish` |
| `publish` | `competency_model_status` 变为 `approved` | job | |
| `skill_classify` | HR 在 SkillLibrary.vue 归类/合并技能 | skill | |
| `manual_fallback` | 用户在 LLM 失败后用扁平字段手填保存 | job | `source=manual_fallback` |
| `embed` | Embedding API 调用 | skill 或 job | 批次中第一个技能的 id 作为 entity_id |

### 3.6 `CompetencyModel` Schema

存于 `app/core/competency/schema.py`（Pydantic）：

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class HardSkill(BaseModel):
    name: str
    canonical_id: int | None = None
    level: Literal["了解", "熟练", "精通"] = "熟练"
    weight: int = Field(ge=1, le=10)
    must_have: bool = False

class SoftSkill(BaseModel):
    name: str
    weight: int = Field(ge=1, le=10)
    assessment_stage: Literal["简历", "IM", "面试"] = "面试"

class ExperienceRequirement(BaseModel):
    years_min: int = 0
    years_max: int | None = None
    industries: list[str] = []
    company_scale: str | None = None

class EducationRequirement(BaseModel):
    min_level: Literal["大专", "本科", "硕士", "博士"] = "本科"
    preferred_level: str | None = None
    prestigious_bonus: bool = False

class AssessmentDimension(BaseModel):
    name: str
    description: str = ""
    question_types: list[str] = []

class CompetencyModel(BaseModel):
    schema_version: int = 1
    hard_skills: list[HardSkill]
    soft_skills: list[SoftSkill] = []
    experience: ExperienceRequirement = ExperienceRequirement()
    education: EducationRequirement = EducationRequirement()
    job_level: str = ""
    bonus_items: list[str] = []
    exclusions: list[str] = []
    assessment_dimensions: list[AssessmentDimension] = []
    source_jd_hash: str                     # SHA256(jd_text)，溯源用
    extracted_at: datetime
    reviewed_by: int | None = None          # users.id（审计用，不加 FK）
    reviewed_at: datetime | None = None
```

### 3.7 种子数据

首批 **50–80 条**主流技能，按类别分（language / framework / cloud / database / tool / soft / domain）。seed migration 填入：
- 有 `AI_API_KEY` 环境：立即调 `embed_batch` 预计算 embedding 写入
- 无 `AI_API_KEY` 环境：`embedding=NULL`，首次被归一化调用时按需懒加载

种子清单作为 `app/core/competency/seed_skills.json` 交付，migration 读取。

### 3.8 老数据懒迁移

| 条件 | UI 行为 |
|---|---|
| `competency_model IS NULL` 且 `jd_text=''` | 要求 HR 先粘贴 JD |
| `competency_model IS NULL` 且 `jd_text!=''` | 显示「从 JD 抽取」按钮 |
| `competency_model` 已有 | 按 status 渲染 |

**不做一次性批量迁移脚本** — 避免一次性 LLM 调用风暴和 HITL 队列被一次灌爆。

---

## 4. 核心流程

### 4.1 端到端流程

```
HR 在 Jobs.vue 能力模型 Tab 填 JD → 点「从 JD 抽取」
                ↓
POST /api/jobs/{id}/competency/extract
                ↓
CompetencyExtractor.extract(jd_text, job_id):
  1. LLM 抽取 (retry 3x, 指数退避 1s/3s/9s, audit: extract)
  2. Pydantic 解析校验 (失败 retry 2x 追加修正提示)
  3. 技能归一化:
     a. 批量 embed (1 次 API 调用)
     b. 对每个技能, 在 SkillCache 找最近邻
     c. 相似度 > 0.85 → 复用 canonical_id, aliases 追加, usage_count++
     d. ≤ 0.85 → INSERT skills (pending_classification=1),
                  创建非阻塞 HITL (F1_skill_classification),
                  audit: normalize (note=new)
  4. 写 jobs.competency_model (status=draft)
  5. 创建阻塞 HITL (F1_competency_review)
                ↓
HR 在 HitlQueue.vue 或 Jobs.vue 能力模型 Tab 审核
                ↓
POST /api/hitl/tasks/{id}/{approve|reject|edit}
                ↓
HitlService.resolve():
  approve:
    competency_model_status → approved
    双写扁平字段 (education_min / required_skills 等)
    audit: hitl_approve, publish
  edit:
    用 edited_payload 覆写 competency_model
    competency_model_status → approved
    双写扁平字段
    audit: hitl_edit, publish
  reject:
    competency_model → NULL
    competency_model_status → rejected
    (draft 快照保留在 hitl_tasks.payload + audit_events, HR 想重抽就看历史)
    audit: hitl_reject
```

### 4.2 LLM 抽取 Prompt

**System message**:

```
你是招聘领域的 HR 专家。给定一段岗位 JD，提取结构化能力模型，严格按 JSON schema 输出。
不要 markdown 包装，不要多余字段。

schema:
{
  "hard_skills": [{"name": str, "level": "了解|熟练|精通",
                   "weight": 1-10, "must_have": bool}],
  "soft_skills": [{"name": str, "weight": 1-10,
                   "assessment_stage": "简历|IM|面试"}],
  "experience": {"years_min": int, "years_max": int|null,
                 "industries": [str], "company_scale": str|null},
  "education": {"min_level": "大专|本科|硕士|博士",
                "preferred_level": str|null, "prestigious_bonus": bool},
  "job_level": str,
  "bonus_items": [str],
  "exclusions": [str],
  "assessment_dimensions": [{"name": str, "description": str,
                             "question_types": [str]}]
}

规则：
1. hard_skills 3–15 条，关键技能 weight 9–10
2. soft_skills 0–8 条
3. assessment_dimensions 2–6 条
4. JD 未提及的字段给空数组 / null，不编造
5. bonus_items = 加分项（"开源贡献"），exclusions = 淘汰项（"不考虑外包"）
```

**User message**：`<jd_text>`

**调用参数**：
- `temperature=0.2`
- `response_format={"type":"json_object"}`（兼容 OpenAI 格式）
- `prompt_version="f1_competency_v1"`（写入 audit_events.prompt_version）
- `model`：`AI_MODEL_COMPETENCY` > `AI_MODEL`（默认 `glm-4-flash`）

### 4.3 重试 + 降级

| 失败类型 | 动作 |
|---|---|
| HTTP 错误 / 超时 | 重试 3 次，指数退避 1s / 3s / 9s |
| JSON 解析失败 | 重试 2 次，追加修正提示"上次输出非合法 JSON，严格按 schema" |
| Pydantic 校验失败 | 同上，重试 2 次 |
| 重试全败 | API 返回 `{status:"failed", fallback:"flat_form"}`，audit: `extract_fail` |

前端收到 `fallback:"flat_form"` → 切到扁平字段手填模式（学历下拉 / 年限 / 技能 CSV），HR 填完保存 → 服务端把扁平字段翻译为最简 `CompetencyModel`（每技能 `weight=5, level=熟练, must_have=false`）→ `competency_model_status=approved` 直接发布（**手填路径不过 HITL**，HR 本人即输入源），audit: `manual_fallback`。

### 4.4 技能归一化

```python
# app/core/competency/normalizer.py
async def normalize_skills(extracted_names: list[str], job_id: int) -> list[dict]:
    vectors = await llm.embed_batch(extracted_names)
    all_skills = SkillCache.all()  # 内存缓存, 启动时加载

    results = []
    for name, vec in zip(extracted_names, vectors):
        best_id, best_sim = find_nearest_cosine(vec, all_skills)
        if best_sim > 0.85:
            bind_alias(best_id, name)
            increment_usage(best_id)
            audit("normalize", entity_type="skill", entity_id=best_id, note="reuse")
            results.append({"name": name, "canonical_id": best_id})
        else:
            new_id = insert_skill(canonical_name=name, embedding=vec,
                                   source="llm_extracted",
                                   pending_classification=True)
            create_hitl_task(f_stage="F1_skill_classification",
                              entity_type="skill", entity_id=new_id,
                              payload={"name": name, "from_job": job_id})
            audit("normalize", entity_type="skill", entity_id=new_id, note="new")
            results.append({"name": name, "canonical_id": new_id})
    return results
```

- `SkillCache` 进程内缓存：启动时全量加载；插入/修改/合并时失效。
- 阈值 `0.85` 写成 `app/core/competency/__init__.py` 常量 `SKILL_SIMILARITY_THRESHOLD`，便于未来调整。

### 4.5 HITL 非阻塞原则

即使有 N 个 `F1_skill_classification` 任务挂着（新技能待归类），阻塞型的 `F1_competency_review` **照样可以审批发布岗位**。归类事后补。前端只在 `SkillLibrary.vue` 显示"N 条待归类"红点提示。

---

## 5. API 表面

### 5.1 能力模型

| Method | Path | 请求体 | 响应 |
|---|---|---|---|
| POST | `/api/jobs/{id}/competency/extract` | — | `{status:"draft"\|"failed", hitl_task_id?, fallback?:"flat_form"}` |
| GET | `/api/jobs/{id}/competency` | — | `{competency_model, status, pending_hitl_task_id?}` |
| POST | `/api/jobs/{id}/competency/manual` | `{flat_fields: {education_min, work_years_min, work_years_max, required_skills, ...}}` — 服务端翻译为最简 CompetencyModel | `{status:"approved"}` |

### 5.2 HITL

| Method | Path | 请求体 |
|---|---|---|
| GET | `/api/hitl/tasks?stage=&status=&limit=&offset=` | — |
| GET | `/api/hitl/tasks/{id}` | — |
| POST | `/api/hitl/tasks/{id}/approve` | `{note?}` |
| POST | `/api/hitl/tasks/{id}/reject` | `{note}` (必填) |
| POST | `/api/hitl/tasks/{id}/edit` | `{edited_payload, note?}` |

### 5.3 技能库

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/skills?category=&pending=&search=&limit=&offset=` | 列表；`search` 走 LIKE，限 20 结果 |
| GET | `/api/skills/categories` | 所有已用分类（下拉数据源） |
| GET | `/api/skills/{id}` | 详情 |
| POST | `/api/skills` | HR 手动新增 `{canonical_name, category, aliases?}`，服务端补 embedding |
| PUT | `/api/skills/{id}` | 改 `canonical_name` / `aliases` / `category` |
| POST | `/api/skills/{id}/merge` | `{merge_into_id}` 合并到另一技能（aliases + usage 转移，原 id 删除） |
| DELETE | `/api/skills/{id}` | 仅 `source=llm_extracted` 且 `usage_count=0` 可删 |

### 5.4 审计（只读）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/audit/events?entity_type=&entity_id=&limit=` | 排查用；默认限 100 条 |

### 5.5 权限

- 所有登录用户（JWT 有效）均可读/写
- 多租户数据隔离按 `user_id` 走（与 M2 现状一致）
- HITL 任务**全局可见**（F1 单团队假设；多租户隔离延至 M4）

---

## 6. 前端

### 6.1 Jobs.vue 能力模型 Tab

**Tab 头部**：JD 原文 textarea + `[从 JD 抽取]` / `[重新抽取]`（approved 后可见）+ 状态指示（none 灰 / draft 黄 / approved 绿 / rejected 红）。

**6 折叠卡片**（默认硬技能 / 经验 / 学历展开，其余折叠）：

| 卡片 | 字段 | 控件 |
|---|---|---|
| 硬技能 | name / level / weight / must_have | Autocomplete（`SkillPicker`） + Select + Slider + Checkbox |
| 软技能 | name / weight / assessment_stage | Input + Slider + Select |
| 经验 | years_min / years_max / industries / company_scale | InputNumber + Tag + Select |
| 学历 | min_level / preferred_level / prestigious_bonus | Radio + Select + Switch |
| 加分 / 淘汰 | bonus_items[] / exclusions[] | Tag + add |
| 考察维度 | name / description / question_types | Input + Textarea + Tag |

**两键模型**（单 HR 友好）：
- `[保存草稿]`：持续编辑，状态 `draft`
- `[通过并发布]`：= edit + approve 一次完成；无改动即走 `approve`；状态 → `approved`，双写扁平字段

### 6.2 HitlQueue.vue

路由 `/hitl`，顶部导航新菜单"审核队列 🔴N"。

- 筛选：`stage` radio + `status` radio + 时间范围
- 列表：类型 / 标题 / 创建时间 / 状态 / 操作
- 「审核」→ 跳 `/jobs?id=X&tab=competency`
- 「归类」→ 跳 `/skills?pending=1&focus=X`

### 6.3 SkillLibrary.vue

路由 `/skills`，顶部导航"技能库"菜单。

- 顶栏：search + category filter + `☑仅待归类 (N)`
- 表格：canonical_name / aliases / category / source / usage_count / 操作（编辑 / 合并 / 删除）
- **批量归类**（高频操作）：多选 pending 行 → `[批量设分类]` 按钮 → 选类别 → 保存
- **合并**：dialog 搜目标技能 → 确认 → 转移 aliases 和 usage → 被合并方 DELETE
- **新增**：弹窗填 canonical_name + category，后端补 embedding

### 6.4 共享组件（`frontend/src/components/` 新起目录）

| 组件 | 用途 | 复用者 |
|---|---|---|
| `SkillPicker.vue` | Autocomplete 技能选择器，支持新建 | F1 硬技能卡片；F2+ 面试评分可能复用 |
| `CompetencyEditor.vue` | 6 卡片编辑器本体 | Jobs.vue 能力模型 Tab 内嵌 |

### 6.5 前端状态管理

- 沿用现状（Composition API 内部管理，无全局 store）
- 新加 `hitlPendingCount` 全局轮询：5 min / 次 + 手动刷新；挂在 App.vue 顶部导航 badge
- 能力模型 Tab 未保存退出：浏览器原生 `beforeunload` 提示

---

## 7. 复用盘点

### 7.1 可复用（直接拿来用）

| 现有代码 | F1 用法 |
|---|---|
| [app/adapters/ai_provider.py](../../app/adapters/ai_provider.py) `AIProvider.__init__` / `is_configured()` / httpx 模式 | 包装到 `core/llm/provider.py`；现类保留做 F2 的 `evaluate_resume` wrapper |
| [app/modules/resume/pdf_parser.py:182](../../app/modules/resume/pdf_parser.py) `_extract_json()` | **搬到** `core/llm/parsing.py`，F1 直接用 |
| [app/modules/resume/_ai_parse_worker.py](../../app/modules/resume/_ai_parse_worker.py) 的后台线程 + asyncio 模式 | 仅参考。F1 单岗位抽取同步即可 |
| [frontend/src/api/index.js](../../frontend/src/api/index.js) axios + JWT 拦截器 + `xxxApi` 模式 | **直接扩**：加 `competencyApi` / `hitlApi` / `skillsApi` |
| [frontend/src/router/index.js](../../frontend/src/router/index.js) | 加 2 个路由 `/hitl`、`/skills` |
| [frontend/src/App.vue](../../frontend/src/App.vue) 侧栏导航 | 加 2 菜单项（审核队列带 badge + 技能库） |
| Element Plus（已装） | 全部 UI 控件复用 |
| [app/database.py](../../app/database.py) `Base` / `SessionLocal` | 复用；`create_tables()` 在 Alembic 引入后改为仅测试用 |

### 7.2 要改造

| 现有代码 | 改造 |
|---|---|
| [app/modules/screening/service.py:52](../../app/modules/screening/service.py) `screen_resumes()` | 优先读 `competency_model`，`NULL` 回退扁平字段（双写兜底） |
| [app/modules/screening/models.py](../../app/modules/screening/models.py) `Job` 模型 | 加 3 列：`jd_text` / `competency_model` / `competency_model_status` |
| [app/modules/screening/schemas.py](../../app/modules/screening/schemas.py) | `JobCreate` / `JobResponse` 加新字段可选输入输出 |
| [frontend/src/views/Jobs.vue](../../frontend/src/views/Jobs.vue) (249 行) | 现表单包进"基本信息" Tab，新加"能力模型" Tab 内嵌 `CompetencyEditor` |
| [app/database.py](../../app/database.py) `create_tables()` | Alembic 引入后改为仅测试用 / 删除 |

### 7.3 全新（F1 从 0 建）

| 模块 | 用途 |
|---|---|
| `app/core/llm/provider.py` | 带重试 + audit 钩子的 LLM 适配层 |
| `app/core/llm/parsing.py` | JSON 响应解析 + Pydantic 校验（含搬来的 `_extract_json`） |
| `app/core/competency/schema.py` | `CompetencyModel` Pydantic 定义 |
| `app/core/competency/extractor.py` | JD → competency_model 全流程 |
| `app/core/competency/skill_library.py` | skills 表 CRUD + SkillCache + seed 加载 |
| `app/core/competency/normalizer.py` | 技能归一化 |
| `app/core/competency/seed_skills.json` | 种子技能清单（50–80 条） |
| `app/core/vector/service.py` | cosine similarity + float32 打包解包 |
| `app/core/hitl/{models,service,router}.py` | HITL 任务管理 |
| `app/core/audit/{models,logger}.py` | audit_events + WORM + 写日志辅助 |
| `migrations/` + `alembic.ini` | 迁移系统（M3-kickoff 独立产出） |
| `frontend/src/components/SkillPicker.vue` | Autocomplete 技能选择器（新起 `components/` 目录） |
| `frontend/src/components/CompetencyEditor.vue` | 6 卡片编辑器 |
| `frontend/src/views/HitlQueue.vue` | 审核队列页 |
| `frontend/src/views/SkillLibrary.vue` | 技能库页 |

### 7.4 关键观察

1. **LLM JSON 抽取的轮子基本有了** — `_extract_json()` + httpx 模式都是现成的；F1 在上面加重试、prompt 版本化、审计钩子、embed_batch。
2. **前端首次起 `components/` 目录** — 现有 7 个 view 全扁平。F1 只放两个组件，不过度组件化。
3. **后台任务机制不复用** — `_ai_parse_worker.py` 是简历批量 AI 解析产物，F1 单岗位同步操作不需要。
4. **审计 / 向量 / HITL / 迁移 全是新基础设施** — 不仅 F1 用，F3/F5/F8 都要用，必须在 F1 一次性建稳。
5. **Embedding 能力实测** — 智谱 `/v1/embeddings` 理论上兼容 OpenAI 响应格式（`{data:[{embedding:[...]}]}`），但需独立任务（T10）实测。

---

## 8. 测试策略

### 8.1 单元测试（`app/core/` ≥ 85%）

| 模块 | 关键测试用例 |
|---|---|
| `core/llm/provider.py` | mock httpx：重试 3 次、指数退避时间、audit 钩子被调；HTTP 500 / 超时 / JSON 解析失败各场景 |
| `core/llm/parsing.py` | 各种 markdown 包装（\`\`\`json / \`\`\` / 无包装）、非法 JSON、合法 JSON |
| `core/competency/schema.py` | Pydantic 边界：weight 0 / 11 / 超范围、level 枚举外值、required 字段缺失 |
| `core/competency/extractor.py` | mock LLM 返回值：成功路径写入 draft + 阻塞 HITL；失败路径 audit `extract_fail` |
| `core/competency/normalizer.py` | mock embed_batch：相似度 0.849 vs 0.851 阈值边界；新技能入库 + 非阻塞 HITL 创建 |
| `core/competency/skill_library.py` | CRUD 幂等；SkillCache 插入失效；seed 重复执行幂等 |
| `core/vector/service.py` | cosine 数学正确（已知向量对）；float32 打包解包往返 |
| `core/hitl/service.py` | approve 分支（含双写扁平字段）；reject 清 draft；edit 覆写；非法状态转换拒绝 |
| `core/audit/logger.py` | **WORM 强约束测试**：INSERT 成功；直接 SQL `UPDATE audit_events ...` 必报 `WORM`；`DELETE` 同样报错 |

### 8.2 集成测试（`tests/modules/screening/` ≥ 80%）

- `test_competency_extract_flow.py`：LLM mock → extract → 能力模型 draft + 1 个阻塞 HITL + N 个非阻塞 HITL（新技能数量）+ audit_events 记点数
- `test_double_write.py`：HITL approve → `jobs.education_min` / `required_skills` / `work_years_min/max` 被回填，值一致性
- `test_flat_backward_compat.py`：M2 老岗位（`competency_model IS NULL`）调 `/screening/jobs/{id}/screen` 行为不变

### 8.3 回归 + 合规

- **零回归底线**：F1 合并前 `pytest tests/` 通过数 ≥ 53（当前基线；`pytest tests/ --tb=no -q` 输出核对）
- **HITL 阻塞测试**：pending 状态下 `competency_model_status` 不可人为切到 `approved`（API 层拒绝）

### 8.4 E2E Smoke

手工或 pytest 驱动一遍：

1. 新建岗位 → 粘 JD → 点「从 JD 抽取」
2. 等服务端返回 draft → HITL 列表显示 1 条 + 新技能 N 条
3. 进能力模型 Tab → 微调权重 → `[通过并发布]`
4. 跑 `/screening/jobs/{id}/screen` → 验证结果与 M2 基线一致 或差异在能力模型权重影响范围内
5. **降级路径**：临时把 `AI_API_KEY` 设成错值 → 抽取失败 → 手填表单 → 保存 → 验证 approved

---

## 9. 任务拆分（29 个任务，TDD 每个一 commit）

### 9.1 M3-kickoff 前置（独立 PR，不计 F1 工时）

| K# | 任务 |
|---|---|
| K0 | 装 Alembic；`alembic init migrations/`；对齐现有 `app/**/models.py` → baseline migration |
| K1 | 本地 + 用户机器 `alembic stamp head` 对齐现数据库；dry-run 在 `recruitment.db` 副本 |

### 9.2 F1 本体

**数据层**（5）

| T# | 任务 |
|---|---|
| T1 | migration: 新建 `skills` 表 + 2 索引 |
| T2 | migration: 新建 `hitl_tasks` 表 + 2 索引 |
| T3 | migration: 新建 `audit_events` 表 + WORM 触发器 + 2 索引 |
| T4 | migration: `jobs` 表加 `jd_text` / `competency_model` / `competency_model_status` 3 列 |
| T5 | data migration: seed 技能（50–80 条，embedding 懒加载策略） |

**core/ 基础设施**（10）

| T# | 任务 |
|---|---|
| T6 | `core/llm/parsing.py` — 搬 `_extract_json` + Pydantic 包装 |
| T7 | `core/audit/{models,logger}.py` — 含 WORM 单测 |
| T8 | `core/vector/service.py` — cosine + float32 打包 |
| T9 | `core/llm/provider.py` — 重试 + audit 钩子；chat completion |
| T10 | `core/llm/provider.py` 扩 `embed_batch()` — **独立实测智谱 `/embeddings` API** |
| T11 | `core/competency/schema.py` — CompetencyModel |
| T12 | `core/competency/skill_library.py` — CRUD + SkillCache + seed 加载 |
| T13 | `core/competency/normalizer.py` |
| T14 | `core/competency/extractor.py` — 串联 T9/T11/T13 |
| T15 | `core/hitl/{models,service,router}.py` |

**业务层**（4）

| T# | 任务 |
|---|---|
| T16 | `screening/{models,schemas}.py` 扩字段 |
| T17 | `screening/service.py` 双写回填逻辑（HITL approve 时触发） |
| T18 | `screening/service.py` 筛选读 `competency_model`，`NULL` 回退扁平 |
| T19 | `screening/router.py` 新 API：`/competency/extract`、`/competency`、`/competency/manual` |

**前端**（8）

| T# | 任务 |
|---|---|
| T20 | `api/index.js` 加 `competencyApi` / `hitlApi` / `skillsApi` |
| T21 | `App.vue` 导航加"审核队列"（badge）+"技能库" |
| T22 | `components/SkillPicker.vue`（新起 `components/` 目录） |
| T23 | `components/CompetencyEditor.vue`（6 卡片） |
| T24 | `views/Jobs.vue` 改造 el-tabs + 嵌入 CompetencyEditor |
| T25 | `views/HitlQueue.vue` |
| T26 | `views/SkillLibrary.vue`（批量归类 + 合并 dialog） |
| T27 | `router/index.js` 加 `/hitl`、`/skills` 路由 |

**集成**（2）

| T# | 任务 |
|---|---|
| T28 | E2E smoke 脚本 / 手工验收清单 |
| T29 | M2 全量回归 + 覆盖率报告 |

**预计工时**：3–4 天（由用户实施节奏决定）

---

## 10. 风险与缓解

| # | 风险 | 可能性 × 影响 | 缓解 |
|---|---|---|---|
| R1 | 智谱 `/v1/embeddings` 响应偏离 OpenAI 标准 | 中 × 高 | T10 独立验证任务；若实测失败，降级方案：用 chat-completion 让 LLM 两两判断同义（慢、贵、准） |
| R2 | Alembic baseline `stamp head` 生产对齐失败 | 中 × 高 | M3-kickoff 文档明写 dry-run 步骤；副本先验证；主库先备份 |
| R3 | SQLite WORM trigger 在某些连接模式下绕过 | 低 × 高 | T7 单测直接 raw SQL `UPDATE/DELETE`；禁用 `PRAGMA ignore_triggers` |
| R4 | 双写时 `education.min_level` 枚举与 M2 `education_min` 对不齐 | 低 × 中 | 枚举值共用"大专/本科/硕士/博士"；T17 单测专项验证 |
| R5 | seed embedding 依赖 `AI_API_KEY`，空配置环境无法启动 | 高 × 低 | 空配置时 `embedding=NULL`；首次归一化时懒加载 |
| R6 | `el-autocomplete` 搜索延迟 | 低 × 低 | 后端 LIKE 索引 + 限 20 结果；前端防抖 300ms |
| R7 | Jobs.vue 大改后 M2 手动测试用例失效 | 中 × 中 | T24 改造后手动过岗位 CRUD；E2E smoke 覆盖 |
| R8 | 并发编辑（HR_A / HR_B 同改同岗位） | 低 × 低 | F1 不处理，后写覆盖前写；M4 加乐观锁 |
| R9 | LLM 幻觉：编造 JD 里没有的技能 | 中 × 中 | prompt 规则 4 明示；HITL 审核兜底；audit 留痕可溯 |
| R10 | competency_model 字段膨胀导致 Jobs.vue 加载慢 | 低 × 低 | 单岗位 JSON ~5KB，可忽略 |

---

## 11. 下一步

1. **本文档 Review（用户）** — 看完 OK 后拍板
2. 批准 → 进入 `superpowers:writing-plans`，产出 `docs/superpowers/plans/2026-04-20-f1-competency-model-plan.md`
3. **并行启动 M3-kickoff**（不阻塞 F1 设计 / 规划）：K0 + K1 两个任务独立做完
4. Plan 完 → 按 29 任务 TDD 逐个推进 → 用户验收

---

## 附录 A：文档交叉引用

- M3 顶层设计：[2026-04-17-m3-autonomous-recruitment-design.md](./2026-04-17-m3-autonomous-recruitment-design.md)
- CLAUDE.md 工作流约束：[../../CLAUDE.md](../../../CLAUDE.md)
- 记忆文件 `feedback_m3_workflow.md` 存于 `C:\Users\neuro\.claude\projects\D--libz-AgenticHR\memory\`
