# M3: 全自动招聘闭环 — 系统级设计文档

**Status**: Draft
**Date**: 2026-04-17
**Phase**: M3
**Supersedes**: N/A (首个多特性阶段)
**Scope**: 顶层架构与跨特性共享基础. 每个 F (F1–F8) 有独立子设计文档.

---

## 1. 背景

### 1.1 现有系统 (M0–M2 已实现)
- **后端**: FastAPI + SQLAlchemy + SQLite (WAL), 5800 LOC, 9 业务模块, 7 外部适配器
- **前端**: Vue 3 + Element Plus + Vite, 8 页面, 2889 LOC
- **扩展**: Edge Manifest V3, 1204 LOC, Boss 直聘批量采集
- **能力**: 登录鉴权 (JWT), 简历采集+PDF 解析, 岗位 CRUD + 硬性条件筛选, AI 一把评分 (OpenAI 兼容), 面试官/面试排期, 多渠道通知, 飞书机器人, 腾讯会议多账号池, Windows 一键 exe

当前链路: **半自动** — HR 每一步手动介入: 人工判定简历是否合适, 人工选面试官, 人工沟通面试时间.

### 1.2 M3 目标
**半自动 → 全自动闭环**. 覆盖需求原文的 7 阶段:
1. AI 到 Boss 直聘界面主动搜索候选人并打招呼
2. 简历批量采集 (沿用 Edge 扩展)
3. AI 简历 vs 岗位 JD 筛选
4. AI 回到 Boss 做第一轮 IM 初筛对话
5. AI 综合对话+简历评估, 符合者进面试
6. 人工选面试官, AI 自动约面+发通知
7. 腾讯会议**文本**分析 + AI 决策建议

### 1.3 约束
- **增量开发**: F1–F8 逐个验证通过再启下一 F. 无并行 F 开发.
- **复用现系统**: 在 `app/modules/*` + `app/adapters/*` 结构上扩, 不重写.
- **腾讯会议本阶段仅文本分析**: 音视频多模态 (情绪/诚信/作弊) 入 backlog, M3 不做.
- **HITL 强制**: 每个自动决策节点必须有人工复核通道 (PIPL §24 红线).
- **合规**: 人社部 2025《AI 招聘算法备案与伦理指引》+ 网信办《AI 生成内容标识办法》+ PIPL + 就业歧视禁令.
- **超能力流程**: 每个 F 走 `brainstorming → writing-plans → tasks → subagent` 链条, TDD 强制.
- **零回归**: M2 已有功能 (硬筛/简历库/约面/飞书通知) 在 M3 内持续可用.

---

## 2. 目标与非目标

### 2.1 Goals
- **G1**: 每个 F 可独立部署/开关. 回退任一 F 不影响已发布 F.
- **G2**: 所有自动决策节点 HITL 覆盖. 生产环境默认开启 HITL, 内测可关.
- **G3**: 审计日志 WORM, 保留 3 年. 字段: 模型版本 / prompt 版本 / 输入 hash / 输出 hash / 复核人 / 时间戳.
- **G4**: 测试驱动. F 合并条件: `pnpm build` + `pytest` 全绿 + 端到端 Demo 通过.
- **G5**: 零回归. 每 F 合并前跑全量 M2 测试集.

### 2.2 Non-goals (延至 M4+)
- 腾讯会议音视频多模态分析 (情绪/诚信/作弊检测)
- 多语种候选人 (英/日)
- 多租户 SaaS 化
- 简历语料自训练 `bge-m3-hr-zh` 双塔
- Roleplay 情景面试题库 (对标牛客)
- 实时语音 AI 面试 (LiveKit)
- 跨渠道聚合 (猎聘/智联/脉脉/拉勾)

---

## 3. 架构

### 3.1 分层策略

M3 引入两类代码:
- **横切基础设施** (M3 新): 能力模型 schema / 技能库 / 向量检索 / LLM 编排 / 审计 / HITL / 合规钩子
- **业务扩展** (M3 新 + 扩现): 每个 F 优先扩现 `app/modules/*`, 只在语义不贴合时新增模块

决定落地方式: 新建 `app/core/` 包承载横切能力, `app/modules/*` 按需扩展.

### 3.2 目录结构扩展

```
app/
├── core/                       # ★ M3 新增 — 横切共享
│   ├── competency/              # 能力模型 schema + 技能库
│   │   ├── schema.py            # Pydantic CompetencyModel
│   │   ├── skill_library.py     # skills 表 CRUD + 种子
│   │   └── normalizer.py        # bge-m3 归一化
│   ├── vector/                  # 向量服务 (本地 bge-m3 或在线 API)
│   │   └── service.py
│   ├── orchestration/           # LangGraph 编排底座
│   │   └── state.py
│   ├── audit/                   # WORM 审计日志
│   │   ├── logger.py
│   │   └── models.py            # audit_events 表
│   ├── hitl/                    # HITL 任务队列
│   │   ├── models.py            # hitl_tasks 表
│   │   ├── service.py
│   │   └── router.py
│   ├── llm/                     # LLM 适配层 (扩 ai_provider)
│   │   └── provider.py
│   └── compliance/              # 合规钩子 (逐 F 落)
│       ├── consent.py
│       ├── bias_audit.py
│       ├── content_label.py
│       └── explainer.py
│
├── modules/                    # 现有模块, 按 F 扩展
│   ├── screening/               # F1: 扩 Job, 加 competency_extractor service
│   ├── resume/                  # F2: 扩 score + 结构化标签
│   ├── boss_automation/         # F3/F4/F6: 叠 Patchright + browser-use
│   ├── ai_evaluation/           # F5/F8: 综合决策扩
│   ├── scheduling/              # F6 面试官侧保留
│   ├── meeting/                 # F7: 新 transcript_analyzer
│   ├── notification/            # F6 飞书通知保留
│   ├── feishu_bot/              # 现有
│   └── auth/                    # 现有
│
└── adapters/                   # 扩展现适配器
    ├── boss/                    # ★ 扩 Patchright agent runner
    │   ├── playwright_adapter.py  # 现有
    │   └── agent_runner.py        # M3 新: browser-use + Patchright
    ├── feishu.py                # 现有
    ├── tencent_meeting_web.py   # 扩云录制 API webhook
    └── asr/                     # ★ F7 新: FunASR 适配
        └── funasr.py
```

### 3.3 F → 模块依赖

| F | 功能简述 | 主模块 | 依赖横切 |
|---|---|---|---|
| F1 | JD → 能力模型 | `screening` 扩 | `core/competency`, `core/llm`, `core/vector`, `core/audit`, `core/hitl` |
| F2 | 简历解析+匹配打分+标签 | `resume` + `ai_evaluation` 扩 | `core/competency`, `core/vector`, `core/llm`, `core/audit` |
| F3 | Boss 主动搜索+打招呼 | `boss_automation` 扩 | `adapters/boss/agent_runner` (Patchright), `core/llm`, `core/audit`, `core/hitl`, `core/compliance/consent` |
| F4 | Boss IM 多轮初筛对话 | `boss_automation` + 新 `interview_im` | `core/orchestration` (LangGraph), `core/llm`, `core/competency`, `core/audit` |
| F5 | 简历+IM 综合评估+推荐 | `ai_evaluation` 扩 | `core/llm`, `core/competency`, `core/audit`, `core/hitl`, `core/compliance/explainer` |
| F6 | 自动约面 Boss+飞书 | `scheduling` + `notification` + `boss_automation` | — |
| F7 | 腾讯会议转录+文本分析 | `meeting` 扩 | `adapters/asr/funasr`, `core/llm`, `core/competency`, `core/audit` |
| F8 | 最终决策建议 | `ai_evaluation` 扩 | `core/llm`, `core/competency`, `core/audit`, `core/hitl`, `core/compliance/explainer` |

### 3.4 端到端数据流

```
[JD 文本]
    ↓ F1: LLM 拆解 + 技能归一 → 能力模型 JSON (存 jobs.competency_model)
    ↓ HITL: HR 审核/改权重/删项
[已发布岗位能力模型 V]
    ↓
F3: Boss 关键词搜候选人 → LLM 生成打招呼话术 → HITL 批准 → 发送
    ↓ (候选人采简历 — 沿用现 Edge 扩展)
F2: PDF → pdfplumber/Qwen-VL → 结构化简历 → bge-m3 与能力模型匹配 → 分项得分 + 证据片段 + 标签
    ↓
候选人回复 → F4: LangGraph state machine → 按考察维度生成问题 → 多轮 IM → transcript
    ↓
F5: 简历 + IM + 证据 → LLM + Prometheus rubric → 推荐决策 → HITL HR 审阅
    ↓
通过 → F6: Boss IM 候选人 + 飞书面试官 → 腾讯会议创建
    ↓
面试 → 腾讯会议云录制 webhook → F7: FunASR 转录 → 按 rubric 文本分析 → 能力评估
    ↓
F8: 简历 + IM + 面试 → LLM + rubric → 录用/待定/拒绝 → HITL HR 最终决策
    ↓
[结果 + 证据链] → audit_events (WORM 3 年)
```

### 3.5 能力模型 Schema (顶层定义, F1 详化)

存于 `app/core/competency/schema.py`:

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class HardSkill(BaseModel):
    name: str                                       # LLM 原抽取名
    canonical_id: int | None = None                 # 关联 skills 表
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
    name: str                    # 例: "系统设计"
    description: str = ""
    question_types: list[str] = []

class CompetencyModel(BaseModel):
    schema_version: int = 1
    hard_skills: list[HardSkill]
    soft_skills: list[SoftSkill]
    experience: ExperienceRequirement
    education: EducationRequirement
    job_level: str = ""
    bonus_items: list[str] = []
    exclusions: list[str] = []
    assessment_dimensions: list[AssessmentDimension]
    source_jd_hash: str          # SHA256(JD 文本), 重算溯源
    extracted_at: datetime
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
```

`jobs` 表扩 `competency_model JSON NULL` 列. 现扁平字段 (`required_skills`, `education_min` 等) 进入"过渡期保留 + M3 结束移除"计划 (F1 实施时评估具体时机).

### 3.6 技能库 (shared, 由 F1 建立)

表结构:
```sql
CREATE TABLE skills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT UNIQUE NOT NULL,   -- "Python"
  aliases JSON,                           -- ["python3", "Py"]
  category TEXT,                          -- "language" / "framework" / "cloud" / "database" / ...
  embedding BLOB,                         -- bge-m3 向量 (1024 × float32)
  source TEXT,                            -- "seed" | "llm_extracted"
  usage_count INTEGER DEFAULT 0,
  created_at DATETIME,
  updated_at DATETIME
);
CREATE INDEX idx_skills_category ON skills(category);
```

**归一化流程**:
1. LLM 输出 `{"name": "Py后端"}` 类原名
2. `normalizer.normalize(name)`:
   - bge-m3 embed(name)
   - 在 skills 表最近邻 (余弦)
   - 相似度 > 0.85 → 绑定 `canonical_id`, 原 name 加入 aliases (若不在), usage_count++
   - ≤ 0.85 → 插入新记录, source="llm_extracted", 标记待 HR 归类
3. 前端 HITL 页可合并/拆分/改类别

**种子数据**: F1 实施时从 roadmap.sh (前端/后端/全栈/DevOps/Mobile) + 公开 IT 技能列表整理 300-500 条, source="seed".

### 3.7 LLM 适配层

现 `adapters/ai_provider.py` 单方法 `evaluate_resume`. M3 替换为 `core/llm/provider.py`:

```python
class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict],
        response_format: Literal["text", "json"] = "text",
        temperature: float = 0.3,
        prompt_version: str = "",   # 审计
    ) -> str: ...

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

class OpenAICompatibleProvider(LLMProvider):
    # 支持智谱 / DeepSeek / 百炼 / Moonshot / 混元
    ...

class LocalBgeM3Provider(LLMProvider):
    # 仅 embed_batch, 本地 sentence-transformers
    ...
```

所有 LLM 调用经此层, 自动写审计日志. 现 `AIProvider` 作为 `OpenAICompatibleProvider` wrapper 保留向后兼容.

### 3.8 编排层 (LangGraph)

F4 IM 对话 / F5 评估 / F8 决策为多节点状态机. 引入 `langgraph` 作编排底座.

`core/orchestration/state.py`:
```python
class RecruitmentState(TypedDict):
    job_id: int
    resume_id: int | None
    competency_model: dict
    im_transcript: list[dict]
    interview_transcript: str
    scores: dict
    evidence: list[dict]
    stage: Literal["sourcing", "greeting", "im_screening", "evaluation", "scheduling", "interview", "decision"]
    hitl_gates: dict[str, Literal["pending", "approved", "rejected", "skipped"]]
```

每个 F 在自己的模块内建 graph 消费 state. 图节点通过 `core/llm` 调模型.

### 3.9 HITL 闭环

表结构:
```sql
CREATE TABLE hitl_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  f_stage TEXT NOT NULL,           -- "F1_competency_review" / "F3_greeting_approve" / ...
  entity_type TEXT,                 -- "job" / "resume" / "im_session" / "interview"
  entity_id INTEGER,
  payload JSON NOT NULL,            -- 待复核内容快照
  status TEXT DEFAULT 'pending',    -- pending | approved | rejected | edited
  edited_payload JSON,              -- HR 改动版本
  reviewer_id INTEGER,
  reviewed_at DATETIME,
  note TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_hitl_status ON hitl_tasks(status);
CREATE INDEX idx_hitl_stage ON hitl_tasks(f_stage);
```

前端新增 `HitlQueue.vue` 全局审任务页, 按 `f_stage` 过滤. 每 F 消费对应 stage.

配置开关: `.env` 增 `HITL_STAGES="F1,F3,F4,F5,F8"` 默认全开, 仅内测可选关.

### 3.10 审计 (WORM)

`core/audit/logger.py` 写 `audit_events` 表. 严格 append-only, DB 级禁 `UPDATE/DELETE` (SQLite trigger 拒绝).

字段:
```sql
CREATE TABLE audit_events (
  event_id TEXT PRIMARY KEY,       -- uuid
  f_stage TEXT,
  action TEXT,                      -- extract | normalize | score | greet | chat | decide | analyze
  entity_type TEXT,
  entity_id INTEGER,
  input_hash TEXT,                  -- SHA256(输入 payload)
  output_hash TEXT,
  prompt_version TEXT,
  model_name TEXT,
  model_version TEXT,
  reviewer_id INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  retention_until DATETIME          -- 默认 +3 年
);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'WORM'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events FOR EACH ROW BEGIN SELECT RAISE(FAIL, 'WORM'); END;
```

所有 `core/llm/provider.py` 调用自动记. 原始输入/输出 payload 存对象存储 (MVP 期写本地 `data/audit/` 目录, M5 迁 MinIO).

### 3.11 合规钩子 (逐 F 落)

`core/compliance/` 按需激活:
- `consent.py`: 候选人首次 IM 打招呼前告知"AI 参与筛选, 可要求人工"+ 记录同意 (F3 激活)
- `content_label.py`: 所有 LLM 输出追加"[AI 生成]" 标识 (F3/F4 激活, 对外消息)
- `bias_audit.py`: 季度批量任务, 分析性别/年龄/院校/地域筛选通过率差异, 写报告 (F5 激活)
- `explainer.py`: 决策伴生证据链 (命中哪个技能/扣分原因) (F5/F8 激活)

### 3.12 前端扩展

新页:
- **JobCompetency.vue** (F1): 能力模型可视化编辑器. 卡片列 hard_skills/soft_skills/experience/education/assessment_dimensions, HR 可增删改权重.
- **HitlQueue.vue** (F1 起): 全局 HITL 待审列表, stage 过滤.
- **SkillLibrary.vue** (F1): 技能库管理页. 合并/归类/查询技能.
- **BossSourcing.vue** (F3): AI 搜索结果列表 + 打招呼话术预览 + 批量批准.
- **ImChats.vue** (F4): 候选人 IM 对话回放 + 多轮评估面板.
- **CandidateReport.vue** (F5): 综合评估报告 (简历+IM) + 决策建议 + 证据链.
- **InterviewTranscript.vue** (F7): 转录回放 + 能力维度打分.
- **FinalDecision.vue** (F8): 最终决策 + 合并所有证据.

扩现页:
- `Jobs.vue`: 新增"能力模型" Tab, 显示模型摘要 + 最新版本.
- `Resumes.vue`: 新增"标签"列 + 匹配分分项展开.
- `Interviews.vue`: 新增"转录+评分" Tab.

### 3.13 数据库迁移

现用 `app/database.py::create_tables()` 启动自动建表. M3 加模块多, 表/列变更频, **M3 启动时引入 Alembic**:
- 初始化 baseline migration = 现 schema 快照
- F 每次 schema 变化出一个 migration
- CI 强制新 migration 可前后兼容测试

风险: 首次 Alembic 落地要跑一次 `alembic stamp head` 对齐生产环境, 不当会导致启动失败. M3 kickoff 任务专门做此.

---

## 4. 测试策略

- **TDD 强制** (CLAUDE.md 约束): 每 F 先写失败测试再实现
- **单元测试**: `core/*` 覆盖率 ≥ 85%, 模块扩展 ≥ 80%
- **集成测试** per F: happy path + HITL 拒绝路径 + 审计日志校验
- **合规回归**: 每 F 必测审计写入 + HITL 拦截 + content_label
- **端到端测试**: 每 F 合并前跑从 JD → 当前 F 结束的 pipeline smoke
- **性能基线**: F2 简历匹配 P95 < 3s (本地 bge-m3) 或 < 10s (在线 API)

---

## 5. 依赖与部署

### 5.1 新依赖 (requirements.txt 增量)
| 依赖 | 用途 | 引入 F | 备注 |
|---|---|---|---|
| `alembic` | schema migration | M3 kickoff | — |
| `sentence-transformers` + bge-m3 模型 | 本地 embedding | F1 | 可选, 在线 API fallback |
| `langgraph` | 编排 | F4 | — |
| `patchright` | Playwright drop-in 反检测 | F3 | 替换现 Playwright |
| `browser-use` | Agent 浏览器编排 | F3 | — |
| `funasr` | 中文 ASR | F7 | CPU/GPU 均可 |
| `prometheus-eval` | Rubric 评估 | F5 | 可选 |

### 5.2 部署影响
- bge-m3 模型 ~2GB, 本地加载内存压力. 生产推荐在线 embedding API (通义/智谱 embedding), 本地仅 fallback.
- PyInstaller 打包体积 +200-500MB, 考虑拆 "基础版 / AI 全量版" 两个 exe.
- GPU 非必需. F7 FunASR CPU 可跑但慢, 建议服务端配 GPU.

---

## 6. 风险与假设

| ID | 风险 | 缓解 |
|---|---|---|
| R1 | Boss 反爬升级, F3/F4 频繁返工 | `adapters/boss/` 抽象接口, Patchright 可替换底座, 节流 < 50/日 |
| R2 | LLM 输出幻觉, 能力模型不准 | HITL 必经 + prompt 版本化 + 黄金集回归测试 |
| R3 | SQLite WAL 在高并发 embedding 写入瓶颈 | 技能库写入限速, M5 迁 PostgreSQL |
| R4 | Alembic 首次落地迁移失败 | M3 kickoff 独立任务, baseline stamp 严格测试 |
| R5 | bge-m3 本地内存压力 | 优先在线 embedding API |
| R6 | 现扁平字段 (`required_skills` 等) 过渡移除节奏 | F1 实施时定时机, 过渡期双写, M3 末清理 |
| R7 | **反爬虫**: Boss ToS + PIPL + 小号隔离 + 拒做大规模采集 |

---

## 7. F 开发顺序 (已与用户确认)

**增量, 一个验证通过再启下一个. 无并行 F**.

F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8

每个 F 独立 design doc: `docs/superpowers/specs/2026-MM-DD-f{N}-<topic>-design.md`.

---

## 8. M3 决策记录

### F1 brainstorm 已确认 (转移至 F1 design doc)
| 决策 | 选项 | 理由 |
|---|---|---|
| 能力模型定位 | B: 单一来源, 替换原扁平字段 | 下游消费统一 |
| 存储 | A: 扩 Job 加 JSON 列 | 主消费方是 LLM, 关系查询弱需求 |
| JD 拆解方式 | B: LLM + 技能库归一化 | 技能名规范便于统计 |
| 技能库来源 | B: 种子 + 自生长 | 冷启动有标准, 自然演化 |

### 横切决策
| 决策 | 选择 | 理由 |
|---|---|---|
| 新代码位置 | `app/core/` 包 | 现模块保 CRUD, 横切隔离 |
| 编排框架 | LangGraph | 状态机+回滚, 与 LangChain 生态一致 |
| 反检测底座 | Patchright | Chromium-only, 反 CDP 指纹, Playwright drop-in |
| 中文 ASR | FunASR | Apache-2.0, 中文 SOTA, 商用免费 |
| Embedding | bge-m3 (本地/API 双模) | 中文 SOTA, 8192 token, 混合检索 |
| Agent 框架 | browser-use | Python + Playwright, 88k★ MIT |
| 数据库迁移 | Alembic, M3 kickoff 引入 | 多 F schema 变化频 |

---

## 9. M4+ Backlog (显式延后)

- 腾讯会议音视频分析 (情绪/诚信/作弊)
- 多语种候选人支持
- 多租户 SaaS 化
- 简历语料自训练 `bge-m3-hr-zh` 双塔
- Roleplay 情景面试题库
- 实时语音 AI 面试 (LiveKit Agents)
- 跨渠道聚合 (猎聘/智联/脉脉/拉勾)
- 人社部 AI 招聘算法备案流程

---

## 10. 下一步

1. 本文档 Review (用户)
2. 批准 → 进入 **F1 专属 brainstorm → design doc → writing-plans → tasks → subagent**
3. F1 设计文档路径: `docs/superpowers/specs/2026-04-XX-f1-competency-model-design.md`
4. M3 kickoff 独立任务 (并行于 F1): Alembic 引入 + baseline migration (不阻塞 F1)
