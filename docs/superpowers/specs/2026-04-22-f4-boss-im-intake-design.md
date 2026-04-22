# F4 设计：Boss IM 候选人信息收集

**Status**: Draft — pending user review
**Date**: 2026-04-22
**Phase**: M3 / F4
**Prereqs**: F1 完成（Job.competency_model + assessment_dimensions）、F2 完成（matching scorer）、F3 完成（Boss 推荐打招呼 + Playwright adapter）

---

## 1. 目标

把 HR 在 Boss 直聘 `https://www.zhipin.com/web/chat/index` 与所有候选人对话中"逐个加微信问硬性条件、催简历、拉家常"的链路自动化：

- 后端 Playwright 守护进程定时扫描所有对话，识别"未入库"候选人
- 对每个候选人收集三类信息：硬性条件（到岗/空闲/实习时长）、PDF 简历、软性问答
- 已能在历史对话中提取的信息直接采集，不重复提问；缺失的字段批量发问，不阻塞等待
- 信息齐全 → 入 `resumes` 表 status=passed → F5 接手
- 全程 0 HITL 审批（用户明确要求）；硬性 3 次问不到改"标记 pending_human + 入库"，留人工兜底

**不含**：F1 能力模型编辑、F5 综合评估、F6 自动约面、给候选人推送推广话术、向新候选人主动打招呼（F3 干）。

---

## 2. 作用域

### In-scope
1. 新模块 `app/modules/im_intake/`（router + service + schemas + scheduler + slot_filler + question_generator + answer_parser）
2. 复用 `app/adapters/boss/playwright_adapter.py`（已有 `get_chat_messages` / `download_pdf` / 求简历按钮 / tab 切换 / 反检测），扩展少量方法（见 §6）
3. 新表 `intake_slots`（candidate × slot 进度）+ `Resume` 加 `intake_status` 字段
4. Alembic 迁移 `0011_im_intake.sql`
5. APScheduler 定时 job（默认 15min）+ 单例 PlaywrightBossAdapter 锁
6. LLM 复用 `core/llm/provider.py`，新增 `ai_model_intake` env（为空回退 `ai_model`）
7. 前端 `Intake.vue` + 路由 + API client
8. 审计：`audit_events` stage=`F4_*`

### Out-of-scope
- HITL 审批（用户明确要求 0 HITL）
- 主动给新候选人打招呼（F3 已做）
- IM 多轮深度对话（F4 只问固定/能力维度问题，不展开追问）
- LangGraph 状态机（F4 状态简单到 enum 即可，不上 LangGraph）
- 候选人撤回/回避意图理解（pending_human 兜底）
- F5 综合评分

---

## 3. 决策表（Q1–Q6 锁定）

| # | 决议 | 说明 |
|---|---|---|
| Q1 执行环境 | **A** Playwright 后端守护 + APScheduler | 复用 F3 adapter，定时扫不依赖 HR 在线 |
| Q2 数据存储 | **C** Resume 早建（仅 boss_id+name）+ `intake_slots` 副表 | 每 slot 独立 asked/answered 时间戳，问了没答天然可查 |
| Q3 完成规则 | 硬性 3 项必须（重问 2 次仍无答→入库标 `pending_human`）；PDF 必须（求简历 1 次，72h 无 → `abandoned`）；软性可选 | 用户确认 |
| Q4a 扫描频率 | **15 min** | APScheduler interval trigger |
| Q4b 单批上限 | 50 人 / 批；共用 `boss_max_operations_per_day` | 防卡死 + 防总量超限 |
| Q4c 浏览器互斥 | **单例 PlaywrightBossAdapter + asyncio.Lock**；F3 手动触发抢锁优先 | 同一 user_data_dir 不冲突 |
| Q5a 提问 | 硬性：3 套预设话术写死；软性：LLM 基于 `assessment_dimensions` + 简历生成 1–3 个 | 不依赖 LLM 的部分越少越好 |
| Q5b 解析 | 先 regex/规则尝试（日期/时段/时长），失败兜底 LLM | 省 token，快 |
| Q5c 批次 | 分两轮发：① 硬性 3 项打包一条 + 求简历 → ② 候选人首回后解析 + 缺啥重问 + 软性合并一条 | 防机器人感 |
| Q6 前端 | `Intake.vue` 列表 + 展开式 slot 详情 + 控制栏（暂停/手动扫一次/cap 余量） | 用户确认 mockup |

---

## 4. 架构

```
┌────────────────────────────────────────────────────────────┐
│  APScheduler (interval=15min)                              │
│      │                                                     │
│      ▼                                                     │
│  IntakeScheduler.tick()                                    │
│      ├─ acquire BossAdapter lock                           │
│      ├─ adapter.list_chat_index() → all candidates         │
│      ├─ for each candidate (cap=50):                       │
│      │    └─ IntakeService.process_one(boss_id)            │
│      └─ release lock                                       │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  IntakeService.process_one(boss_id)                        │
│   1. ensure_resume_row(boss_id, name)  ─→ resumes 行       │
│   2. fetch_history(boss_id) ─→ messages                    │
│   3. SlotFiller.try_extract_from_history(messages, slots)  │
│        regex → LLM 兜底, 填到 intake_slots                  │
│   4. PdfCollector.try_collect()                            │
│        a. 已获取简历 tab 检查 → download_pdf                │
│        b. 没拿到 + 未点求简历 → 点 "求简历" 按钮            │
│   5. QuestionGenerator.next_questions()                    │
│        硬性缺 → 模板话术（含重问轮次）                      │
│        软性缺 + 简历到 → LLM 生成                           │
│   6. adapter.send_message(boss_id, packed_question)        │
│   7. evaluate_completion()                                 │
│        硬性问够 3 次 + PDF 齐 → status=passed              │
│        硬性某项问 3 次仍空 → intake_status=pending_human   │
│        72h 无 PDF → intake_status=abandoned                │
│   8. audit_events.write(F4_*)                              │
└────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│  Frontend Intake.vue                                       │
│   - GET  /api/intake/candidates           列表             │
│   - GET  /api/intake/candidates/{id}      详情 + slots     │
│   - PUT  /api/intake/slots/{id}           人工补字段       │
│   - POST /api/intake/candidates/{id}/abandon              │
│   - POST /api/intake/candidates/{id}/force-complete       │
│   - POST /api/intake/scheduler/pause / resume / tick-now  │
└────────────────────────────────────────────────────────────┘
```

---

## 5. 数据模型

### 5.1 `intake_slots` 表（新）

```sql
CREATE TABLE intake_slots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resume_id INTEGER NOT NULL,
  slot_key TEXT NOT NULL,
  slot_category TEXT NOT NULL,
  value TEXT,
  asked_at DATETIME,
  answered_at DATETIME,
  ask_count INTEGER NOT NULL DEFAULT 0,
  last_ask_text TEXT,
  source TEXT,
  question_meta JSON,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX uq_intake_resume_slot ON intake_slots(resume_id, slot_key);
CREATE INDEX idx_intake_resume ON intake_slots(resume_id);
CREATE INDEX idx_intake_answered ON intake_slots(answered_at);
```

字段说明：
- `slot_key`: 枚举 `arrival_date` / `free_slots` / `intern_duration` / `pdf` / `soft_q_<dim_id>_<n>`
- `slot_category`: `hard` / `pdf` / `soft`
- `value`: 文本（结构化值如日期数组也存 JSON 字符串）
- `asked_at` / `answered_at`: 最近一次问/答的时间戳
- `ask_count`: 已问轮次（硬性达 3 触发 `pending_human`）
- `last_ask_text`: 上次发的话术（防重复提问、审计）
- `source`: `from_history`（历史对话已含）/ `regex` / `llm` / `manual`
- `question_meta`: 软性 slot 存 `{dimension_id, dimension_name}`

### 5.2 `resumes` 表新增字段

```sql
ALTER TABLE resumes ADD COLUMN intake_status TEXT NOT NULL DEFAULT 'collecting';
ALTER TABLE resumes ADD COLUMN intake_started_at DATETIME;
ALTER TABLE resumes ADD COLUMN intake_completed_at DATETIME;
ALTER TABLE resumes ADD COLUMN job_id INTEGER;
```

`intake_status` 枚举：
- `collecting`：F4 正在收集
- `awaiting_reply`：已发问，等候选人回复
- `pending_human`：已入库（status=passed），但有硬性字段缺失，需 HR 补
- `complete`：已完整入库
- `abandoned`：72h 无 PDF 或显式拒绝

`job_id`：F4 必须知道当前候选人对应哪个岗位（关联到 Job.competency_model）。识别策略：从 Boss IM 卡片的 `.source-job` 字段抓岗位名 → fuzzy 匹配 system `Job.title`，相似度 < 0.7 跳过该候选人（写日志 `unmatched_job`）。

### 5.3 `audit_events` 新 stage

- `F4_intake_started` — 新候选人入收集流程
- `F4_extract_history` — 从历史对话抠字段
- `F4_question_sent` — 发问成功
- `F4_answer_parsed` — 解析候选人回复
- `F4_pdf_requested` — 点了求简历
- `F4_pdf_received` — PDF 落盘
- `F4_completed` — 入库完成
- `F4_pending_human` — 标记待人工补
- `F4_abandoned` — 放弃

---

## 6. 模块详设

### 6.1 `app/modules/im_intake/`

```
im_intake/
├── __init__.py
├── router.py            # FastAPI 路由
├── schemas.py           # Pydantic
├── service.py           # IntakeService.process_one()
├── scheduler.py         # APScheduler job 注册 + 锁
├── slot_filler.py       # SlotFiller (regex + LLM 兜底解析)
├── question_generator.py # QuestionGenerator (模板 + LLM 软性)
├── pdf_collector.py     # PdfCollector (求简历按钮 + 已获取简历 tab)
├── job_matcher.py       # 岗位名 fuzzy 匹配
├── prompts/
│   ├── parse_hard_v1.txt
│   ├── parse_soft_v1.txt
│   └── soft_question_v1.txt
└── templates/
    └── hard_questions.py  # 3 套硬性话术（首问 / 重问1 / 重问2）
```

### 6.2 `app/adapters/boss/playwright_adapter.py` 扩展

新增方法（保持向后兼容）：
- `list_chat_index() -> list[BossCandidate]` — 切到 chat/index 页扫所有对话条目（不止"新招呼" tab）
- `send_message(boss_id, text) -> bool` — 发普通文字消息（已有 `send_greeting_reply` 内嵌逻辑，抽出来）
- `click_request_resume(boss_id) -> bool` — 抽 `send_greeting_reply` 中的"求简历"按钮逻辑
- `list_received_resumes() -> list[(boss_id, pdf_url)]` — 切到"已获取简历" tab 抓所有 PDF 卡片

### 6.3 SlotFiller — 解析候选人回复

```python
class SlotFiller:
    def try_extract_from_history(self, messages: list[BossMessage], existing_slots: dict) -> dict:
        """对每个未填的 slot：
        1. regex/rule 尝试匹配整段历史消息
        2. 命中 → 返回 {slot_key: (value, source='regex')}
        3. 未命中 → 调 LLM (parse_hard_v1.txt prompt) 给所有未填 slot 一次性解析
        """

    def parse_reply(self, reply_text: str, pending_slot_keys: list[str]) -> dict:
        """候选人单条回复 → 尝试填多个 pending slot"""
```

regex 例子：
- `arrival_date`: `(下?周[一二三四五六日天]|明天|后天|\d+月\d+[号日]|立刻|马上|随时)`
- `intern_duration`: `(\d+\s*个?\s*月|半年|一年|长期)`
- `free_slots`: 抓多组 `(周[一二三四五六日])\s*(上午|下午|晚上)?`

### 6.4 QuestionGenerator

硬性话术（`templates/hard_questions.py`）：
```python
HARD = {
    "arrival_date": [
        "您好~请问您最快什么时候可以到岗呢？",
        "想再确认一下您的入职时间方便告知吗？",
        "麻烦最后确认下到岗时间哦~",
    ],
    "free_slots": [
        "方便告知您接下来五天哪些时段可以面试吗？",
        "想约下面试时间，您这周哪些时段方便？",
        "最后确认下，您这五天内可面试的具体时段~",
    ],
    "intern_duration": [
        "请问您实习能持续多久呢？",
        "想再确认下您可以实习的总时长~",
        "麻烦最后确认下实习时长哦~",
    ],
}
```

软性 LLM prompt（`prompts/soft_question_v1.txt`）：
- 输入：`Job.competency_model.assessment_dimensions` + 候选人简历摘要（PDF 已到时取 `Resume.raw_text` 前 2000 字）
- 输出：JSON `[{"dimension_id": ..., "question": "..."}]`，最多 3 条
- 约束：每个问题 ≤ 60 字，禁忌歧视用语，加 `[AI 生成]` 标识由发送层附加

打包逻辑（service.py）：
- 第一轮（首次接管该候选人）：硬性 3 项合并一条 + 末尾点求简历
  ```
  您好张三~
  我们对接的是【前端开发】岗位，想跟您先确认几个信息：
  1. 您最快什么时候可以到岗？
  2. 接下来五天哪些时段方便面试？
  3. 实习能持续多久？
  ```
- 第二轮（候选人首回后）：解析 → 缺啥重问 + 软性合并一条
  ```
  收到~关于实习时长再确认下方便吗？
  另外想了解：您简历里提到做过 XXX，能讲讲 ... ？
  ```

每条 IM 消息末尾追加 `[AI 助手]` 字符（合规 `content_label`）。

### 6.5 PdfCollector

```python
class PdfCollector:
    async def try_collect(self, boss_id: str, slot: IntakeSlot) -> bool:
        """
        1. 切到 '已获取简历' tab，扫 list_received_resumes()
           命中 boss_id → download_pdf → 落盘 → 触发 _ai_parse_worker
        2. 未命中 + slot.ask_count == 0 → 点 '求简历' 按钮 (adapter.click_request_resume)
        3. 未命中 + asked > 72h → return False, scheduler 标 abandoned
        """
```

PDF 到达后调用现有 `app/modules/resume/_ai_parse_worker.py` 解析填 raw_text/skills 等字段。

### 6.6 IntakeScheduler

```python
class IntakeScheduler:
    _lock: asyncio.Lock  # 全局单例
    _adapter: PlaywrightBossAdapter

    async def tick(self):
        async with self._lock:
            candidates = await self._adapter.list_chat_index()
            batch = self._select_batch(candidates, cap=50)
            for c in batch:
                if self._adapter._operations_today >= settings.boss_max_operations_per_day:
                    break
                try:
                    await IntakeService(db, self._adapter).process_one(c)
                except Exception as e:
                    logger.error(...)

    def pause(self): ...
    def resume(self): ...
    async def tick_now(self): ...  # 手动触发
```

`_select_batch` 优先级：
1. 已发问 + 未答 + 距上次问 ≥ 24h（重问候选）
2. 新候选（resumes 表无对应 boss_id）
3. PDF 待收（已点求简历，定期扫"已获取简历" tab）

F3/F4 共享同一 PlaywrightBossAdapter 单例；F3 用户手动点击触发时直接 `_lock.acquire()`，F4 tick 中检查 `if self._lock.locked(): skip this tick`，避免堆积。

---

## 7. API 设计

```
GET  /api/intake/candidates                  ?status=collecting|...&job_id=...&page=&size=
GET  /api/intake/candidates/{resume_id}      详情 + 全部 slots + 原始对话
PUT  /api/intake/slots/{slot_id}             人工补 value（pending_human 用）
POST /api/intake/candidates/{resume_id}/force-complete
POST /api/intake/candidates/{resume_id}/abandon
GET  /api/intake/scheduler/status            { running, next_run_at, daily_cap_used, daily_cap_max, last_batch_size }
POST /api/intake/scheduler/pause
POST /api/intake/scheduler/resume
POST /api/intake/scheduler/tick-now
```

---

## 8. 前端 `Intake.vue`

布局（详细 mockup 见 brainstorm 对话）：
- 顶部控制栏：调度状态 / 下次扫描倒计时 / cap 余量 / 暂停-恢复-立即扫
- 候选人列表（折叠）：姓名 / Boss ID / 岗位 / 状态徽章 / 进度条 N/5 / 最近活动
- 展开行：硬性 3 项 / PDF 状态 / 软性问答 — 每项展示 AI 提问 + 候选人答 + 时间戳 + 来源
- 操作按钮：看完整对话 / 手动补字段 / 强制入库 / 标记放弃

路由：`/intake` 加到 `Resumes.vue` 同级菜单。

---

## 9. 配置

`.env` 新增：
```
F4_ENABLED=true
F4_SCAN_INTERVAL_MIN=15
F4_BATCH_CAP=50
F4_HARD_MAX_ASKS=3
F4_PDF_TIMEOUT_HOURS=72
F4_SOFT_QUESTION_MAX=3
AI_MODEL_INTAKE=          # 空 = 回退 ai_model；推荐 glm-4-flash / haiku
```

---

## 10. 测试策略（TDD）

### 单元测试
- `slot_filler_test.py` — regex 黄金集 50 条（到岗/时段/时长各 15 条 + 边界 5 条）
- `question_generator_test.py` — 硬性话术按 ask_count 选；软性 prompt 渲染（mock LLM）
- `pdf_collector_test.py` — 已获取简历 tab fixture / 求简历按钮 fixture
- `job_matcher_test.py` — fuzzy 阈值

### 集成测试
- `test_process_one_full_pipeline.py` — 模拟一个候选人从 collecting → complete 全流程
- `test_pending_human_path.py` — 硬性问 3 次无答 → pending_human + 入库
- `test_abandoned_path.py` — 72h 无 PDF → abandoned
- `test_concurrent_lock.py` — F3 抢锁，F4 tick 跳过
- `test_history_extraction.py` — 候选人之前已答某些 slot，不重复问
- `test_audit_events_written.py` — 每个 stage 都写 audit

### 端到端 smoke
- 1 个候选人 fixture（mock Playwright），验证 API 返回数据 + 前端列表 / 详情正确

---

## 11. 风险与假设

| ID | 风险 | 缓解 |
|---|---|---|
| R1 | Boss `chat/index` DOM 变化 | selector 抽常量，加日志，selector breaking 时告警 |
| R2 | LLM 解析候选人回复出错（误填） | 1. 解析结果存 `source` 字段可审计 2. pending_human 给 HR 改 3. 回归测试黄金集 |
| R3 | F3/F4 竞争 daily cap 致 F4 总跑不到 | F4 至少保留 30% cap 给自己（`boss_f4_min_cap_ratio=0.3`） |
| R4 | 软性问题质量差致候选人困惑 | prompt 严控字数 + 禁忌词；前端可手动停某 slot |
| R5 | PDF 自动解析失败 | 沿用现 `_ai_parse_worker` 重试 + 失败标记 ai_parsed=failed，不阻塞 F4 完成 |
| R6 | 同一 boss_id 在 chat/index 多次出现（如多岗位匹配） | UNIQUE(user_id, boss_id) 约束；首次抓到的 job_id 锁定 |
| R7 | 候选人换号/拉黑 | adapter 报错 → mark abandoned + 写 audit |
| R8 | LLM 调用超时拖慢 tick | per-候选人超时 10s；超时跳过本轮，下轮再试 |

---

## 12. 实施顺序（独立任务）

T1. Alembic 迁移 + Resume 字段 + intake_slots 表
T2. PlaywrightBossAdapter 扩展（list_chat_index / send_message / click_request_resume / list_received_resumes）+ 单例 + lock
T3. SlotFiller (regex + LLM 兜底)
T4. QuestionGenerator (templates + soft LLM)
T5. PdfCollector
T6. JobMatcher
T7. IntakeService.process_one() 串起来
T8. IntakeScheduler + APScheduler 注册
T9. FastAPI router + schemas
T10. Frontend Intake.vue + router + API client
T11. 集成测试 + 端到端 smoke
T12. CHANGELOG + 文档

---

## 13. 不做的事（显式延后到 F5+）

- 多轮深度对话（候选人答完软性后追问）
- 简历 + IM 综合评分（F5 干）
- 自动约面（F6 干）
- 同意条款告知 + PIPL consent 流程（F4 不对外发非问候性新消息，沿用现 IM 通道；F5/F6 发面试邀约时再加）
