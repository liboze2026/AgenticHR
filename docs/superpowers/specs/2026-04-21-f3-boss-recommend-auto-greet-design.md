# F3 设计：Boss 推荐牛人自动打招呼

**Status**: Draft — pending user review  
**Date**: 2026-04-21  
**Phase**: M3 / F3  
**Prereqs**: F1 完成（能力模型 + HitlService）、F2 完成（简历匹配 + scorer + canonical_id 消费）

---

## 1. 目标

把 HR 在 Boss 直聘「推荐牛人」页（`https://www.zhipin.com/web/chat/recommend`）的「人工浏览 → 判定是否匹配 → 点打招呼」链路自动化：

- 插件遍历推荐列表，对每个牛人采详情，调本系统 F2 匹配逻辑打分
- 分数 ≥ 岗位配置阈值即点 Boss 页「打招呼」按钮（**不用 LLM 生成话术**，Boss 自带默认话术）
- 全流程可中断、可审计、有反检测与风控熔断

**不含**：简历下载（推荐页无 PDF）、LLM 生成打招呼话术（用 Boss 默认话术）、候选人同意告知（话术非 AI 生成，合规 R7 降级）、点开详情 modal 抓富文本（MVP 不做，见 §5.2 LIST-only 策略）、`F3_AI_PARSE_ENABLED=true` 路径（开关留好，MVP 关闭）。

## 2. 作用域与非作用域

### In-scope
1. 新后端模块 `app/modules/recruit_bot/`（router + service + schemas）
2. `app/modules/screening/models.py` 加 `greet_threshold`（Job 字段，默认 60）
3. `app/modules/resume/models.py` 加 `greet_status` / `greeted_at` 字段 + `UNIQUE(user_id, boss_id)` 约束
4. Alembic 迁移 `0010_recruit_bot.sql` 落上述 schema
5. `edge_extension/popup.html` + `popup.js` 加 F3 section（岗位下拉 + 配额 + 开始/暂停）
6. `edge_extension/content.js` 加 `autoGreetRecommend()` 及所有 DOM 相关逻辑
7. 反检测与风控熔断（见 §7）
8. 审计链路（写 `audit_events`，stage=`F3_*`）

### Out-of-scope
- HITL 审批（F3 无 HitlTask；阈值 + 能力模型预先审过即充分决策）
- Patchright / browser-use（M3 spec 原提案改为仅用现有 Edge 扩展）
- LLM 生成打招呼话术
- 多岗位并发（Q1 A：单 job 单会话）
- Boss 其它入口（搜索页、沟通页）自动化

## 3. 功能决议（Q1-Q9 锁定）

| Q | 决议 | 说明 |
|---|---|---|
| Q1 岗位源 | **A** popup 下拉选系统 job_id | 零歧义，显式选 |
| Q2 匹配位置 | **A** 后端 F2 `MatchingService.score_pair` | 重用 canonical_id + bge-m3 + scorer 五维 |
| Q3 阈值策略 | **B** per-job `greet_threshold` | 与 F2 per-job scoring weights 一致 |
| Q4 HITL | 无 | 阈值 + competency 已是 HR 策略审批；打招呼动作低代价 |
| Q5a 每日上限 | 每 HR 默认 1000，可调 | `resumes.daily_cap` 或 `users.daily_cap`（落 users 表） |
| Q5b 单次上限 | 无 | 跑到推荐底 / cap 打满 / 风控 halt |
| Q5c 节流 | 相邻随机 2-5s，每 10 个长停 3-6s | 用户确认 |
| Q6a 历史已打过 | 跳过 | audit_events 查 F3_greet_sent by boss_id |
| Q6b 已有 resume 未打过 | 复用 resume_id 正常跑 F2 | 省重复建行 |
| Q6c 本次运行内重复 | `processedBossIds: Set` 去重 | content.js 内存集 |
| Q7a AI 解析 | MVP 不跑 | DOM 抠字段给 F2 scorer；开关 `F3_AI_PARSE_ENABLED=false` 后置开启 |
| Q7b 失败入库 | 入库 status=rejected | F5 可用，reject_reason=`F3 分{score}低于阈值{threshold}` |
| Q8 岗位对齐 | **B** 抓 Boss 页岗位名 vs `job.title` 相似度 < 0.7 弹确认 | 防选错岗位 |
| Q9a source | `boss_zhipin` | 平台名，非通道名 |
| Q9b status | matching 通过=passed / 失败=rejected | 与 F2 语义一致 |
| Q9c greet_status | 枚举 `none / pending_greet / greeted / failed / skipped` + `greeted_at` | 与 resume status 解耦 |
| Q9d UNIQUE(user_id, boss_id) | 强约束 | 防重复建行 |

## 4. 架构

```
┌─────────────────────────────────────────────────┐
│  Edge 扩展                                      │
│  ┌─────────┐    ┌─────────────────────────┐    │
│  │ popup   │───▶│ content.js              │    │
│  │ (UI)    │    │  - autoGreetRecommend() │    │
│  │         │    │  - scrape 推荐卡片       │    │
│  │         │    │  - click 打招呼按钮      │    │
│  └────┬────┘    │  - pause/resume/halt    │    │
│       │         └────────┬────────────────┘    │
└───────┼──────────────────┼──────────────────────┘
        │                  │
        ▼                  ▼
     /api/screening/jobs  /api/recruit/*
        │                  │
┌───────┼──────────────────┼──────────────────────┐
│   FastAPI 后端                                  │
│  ┌────────────────────────────────────┐         │
│  │ app/modules/recruit_bot/           │         │
│  │   router.py (3 endpoints)          │         │
│  │   service.py (核心编排)            │         │
│  │   schemas.py                       │         │
│  │                                    │         │
│  │ 依赖:                              │         │
│  │  • screening.Job (greet_threshold) │         │
│  │  • resume.Resume (upsert+greet)    │         │
│  │  • matching.MatchingService        │         │
│  │  • core.audit.log_event            │         │
│  └────────────────────────────────────┘         │
└─────────────────────────────────────────────────┘
```

**改动边界**：后端纯加法（新模块 + 新字段），前端插件纯加法（新 section + 新 handler），无破坏性变更。`boss_automation` / `core/hitl` 不动。

## 5. 组件

### 5.1 后端 `app/modules/recruit_bot/`

#### router.py — 4 个端点（JWT required，current_user scope）

- `POST /api/recruit/evaluate_and_record`  
  入：`{job_id, candidate: ScrapedCandidate}`  
  出：`RecruitDecision`（见下）

- `GET /api/recruit/daily-usage`  
  出：`{used, cap, remaining}`

- `PUT /api/recruit/daily-cap`  
  入：`{cap: int}`  
  出：`{cap}`

- `POST /api/recruit/record-greet`  
  入：`{resume_id, success, error_msg}`  
  出：`{status: "recorded"}`

#### service.py 主函数

```
evaluate_and_record(db, user_id, job_id, scraped) -> RecruitDecision:
  1. if get_daily_usage(db, user_id).remaining <= 0:
       return RecruitDecision(decision="blocked_daily_cap", ...)

  2. resume = upsert_resume_by_boss_id(db, user_id, scraped)
     if resume.greet_status == "greeted":
       return RecruitDecision(decision="skipped_already_greeted",
                              resume_id=resume.id, ...)

  3. job = db.query(Job).filter(id=job_id, user_id=user_id).first()
     if not job: raise 404
     if not job.competency_model:
       return RecruitDecision(decision="error_no_competency", ...)

  4. threshold = job.greet_threshold or DEFAULT_THRESHOLD (60)
     score_result = MatchingService.score_pair(db, resume.id, job_id)
     score = score_result.total_score

  5. if score >= threshold:
       resume.status = "passed"
       resume.greet_status = "pending_greet"
       log_event(f_stage="F3_evaluate", action="should_greet", ...)
       return RecruitDecision(decision="should_greet",
                              resume_id=resume.id, score=score, threshold=threshold)
     else:
       resume.status = "rejected"
       resume.reject_reason = f"F3 分{score}低于阈值{threshold}"
       log_event(f_stage="F3_evaluate", action="rejected_low_score", ...)
       return RecruitDecision(decision="rejected_low_score", ...)

record_greet_sent(db, user_id, resume_id, success, error_msg=""):
  resume = db.query(Resume).filter(id=resume_id, user_id=user_id).first()
  if not resume: raise 404
  if resume.greet_status == "greeted":
    return  # 幂等 noop
  if success:
    resume.greet_status = "greeted"
    resume.greeted_at = datetime.now(timezone.utc)
    log_event(f_stage="F3_greet_sent", action="greet_sent", ...)
  else:
    resume.greet_status = "failed"
    log_event(f_stage="F3_greet_failed", action="greet_failed",
              output_payload={"error": error_msg})

get_daily_usage(db, user_id) -> UsageInfo:
  today = local_today_start()  # 00:00 Asia/Shanghai
  used = db.query(Resume).filter(
    user_id=user_id,
    greet_status="greeted",
    greeted_at >= today
  ).count()
  cap = db.query(User).filter(id=user_id).first().daily_cap or 1000
  return UsageInfo(used=used, cap=cap, remaining=cap - used)
```

#### schemas.py

```python
class ScrapedCandidate(BaseModel):
    name: str
    boss_id: str                        # Q9 D1 要求非空; (user_id, boss_id) UNIQUE
    age: int | None = None
    education: str = ""                 # "硕士" / "本科" / "大专" …
    grad_year: int | None = None        # 从 "27年应届生" 解出 2027
    work_years: int = 0                 # 应届=0; 否则从最近工作条目起算
    school: str = ""                    # "北京交通大学"
    major: str = ""                     # "软件工程"
    intended_job: str = ""              # "全栈工程师"（从"最近关注"抠）
    skill_tags: list[str] = []          # ["Spring","后端开发","Redis"] — F2 skill scorer 核心
    school_tier_tags: list[str] = []    # ["211院校","985院校"]
    ranking_tags: list[str] = []        # ["专业前20%","专业前5%"]
    expected_salary: str = ""           # "3-4K" / "面议" / "5-8K"
    active_status: str = ""             # "刚刚活跃" / "在线" / ""
    recommendation_reason: str = ""     # "来自相似职位Python" 等，可空
    latest_work_brief: str = ""         # "2024.09 - 2024.11 公司 · 岗位" 或 ""
    raw_text: str = ""                  # 上述字段拼接，调试留痕，非必填
    boss_current_job_title: str = ""    # Q8 对齐检查，从页面顶部下拉抓

class RecruitEvaluateRequest(BaseModel):
    job_id: int
    candidate: ScrapedCandidate

class RecruitDecision(BaseModel):
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
```

### 5.2 Scraping 策略 — LIST-only（2026-04-21 live 探查后定案）

Boss 推荐页点卡片会打开**详情 modal**（含自我介绍、工作经历描述段、项目经验、经历概览）；信息比 list card 丰富很多。**但 MVP 不用 modal**：

**选 LIST-only 理由**：
1. F2 scorer 吃结构化字段（skill/edu/years/intended_job/industry），list card 已覆盖全部核心（skill_tags / school / major / grad_year / intended_job / expected_salary）
2. Modal 的简介段落 / 工作描述文本是非结构化 raw_text，F2 scorer **不直接消费**（只有 Q7a `F3_AI_PARSE_ENABLED=true` 时 LLM 解析才用，MVP 关闭）
3. 交互次数：LIST-only 1 次 click 即完成（直接点 list "打招呼"）；Modal 需 4 次（点开+等加载+关+返回定位）
4. 单次 100 人：LIST-only ≈ 6-7 分钟；Modal ≈ 17-20 分钟。反检测窗口期大大缩短
5. Modal 路径将来 `F3_AI_PARSE_ENABLED=true` 打开时作为 opt-in 扩展点

**LIST card 字段完整性**（live 观察结果）：
- 头像 + 薪资 tag
- 姓名 / 年龄 / 毕业年 / 学历 / 活跃状态
- "最近关注" 行 (城市 · 岗位名 · 行业)
- "学历" 行 (学校 · 专业 · 学位)
- 工作经历简述 1 条（有则"YYYY.MM - YYYY.MM 公司 · 岗位"，无则"未填写工作经历"）
- Tag 行（所有这些 tag 混排）：院校 tag / skill tag / 排名 tag / 推荐理由 tag
- 右侧"打招呼"按钮

**T1 live 探查任务**固定为：
- list card 容器 selector
- 各字段 sub-selector（薪资/姓名/年龄/最近关注/学校/skill tags 分类逻辑/"打招呼"按钮）
- 打招呼后按钮 DOM 变化标志（文案变/disable/消失）
- 列表滚动加载机制（容器 scroll vs window scroll；触底触发 vs 按钮加载）
- 风控弹窗 selector 集（§7.3）

### 5.3 前端扩展

#### popup.html 新增 section

```html
<div class="section">
  <div class="section-title">F3 推荐牛人自动打招呼</div>
  <select id="recruitJobSelect"><option>加载岗位...</option></select>
  <div class="usage-bar">已打 <span id="usageUsed">0</span>/<span id="usageCap">1000</span>
    <a href="#" id="editCap">修改</a></div>
  <button id="btnRecruitStart" class="btn btn-primary">开始自动打招呼</button>
  <div id="recruitStats"></div>
</div>
```

#### popup.js 新函数
- `loadJobs()` — 初始化调 `/api/screening/jobs?active_only=1` 填下拉
- `loadDailyUsage()` — 调 `/api/recruit/daily-usage` 渲染配额
- `startAutoRecruit()` — 校验后向 content.js 发 `action=autoGreetRecommend`
- `editCap()` — prompt 弹输入，调 `/api/recruit/daily-cap` PUT

#### content.js 新函数
- `autoGreetRecommend({ jobId, serverUrl, authToken })` 主循环
- `scrapeRecommendCard(cardEl) -> ScrapedCandidate` DOM 抠字段（T1 探 selector）
- `findGreetButton(cardEl) -> HTMLElement|null`
- `simulateHumanClick(el)`（见 §7 反检测）
- `detectRiskControl() -> bool`（见 §7）

## 6. 数据流（Happy Path 单候选人）

```
popup.startAutoRecruit
    │ action=autoGreetRecommend,jobId,serverUrl,token
    ▼
content.js autoGreetRecommend
    │ 1. 岗位对齐检查（Q8 B）
    │ 2. loadCardList() — 推荐列表 DOM 查
    │ for each card:
    │   3. waitIfPaused + 随机 2-5s sleep（Q5c）
    │      每 10 个长停 3-6s
    │   4. scrollIntoView + mouseover 200ms（§7 反检测）
    │   5. scrape 卡片字段（LIST-only，不开 modal — §5.2）
    ▼
POST /api/recruit/evaluate_and_record
    │ 后端 evaluate_and_record:
    │   • daily_cap 检查
    │   • upsert resume (UNIQUE user_id,boss_id)
    │   • 已 greeted skip
    │   • MatchingService.score_pair (F2 逻辑)
    │   • 更新 status + greet_status
    │   • audit_events
    ▼
decision
    │
    ├─ should_greet:
    │    simulateHumanClick(greetBtn)
    │    等 Boss DOM 反馈（按钮文案变 "已打招呼" 或 dialog）
    │    POST /api/recruit/record-greet success/failed
    │
    ├─ skipped_already_greeted / rejected_low_score / error_no_competency:
    │    记 log，继续下一个
    │
    ├─ blocked_daily_cap:
    │    halt + popup 提示
    │
    └─ error_*:
         记 log 继续（error_no_competency 例外 halt）
```

## 7. 反检测与风控熔断（硬约束）

### 7.1 操作频率
- 相邻候选人间隔 **随机 2-5 秒**
- 每打 **10 个** 强制长停 **3-6 秒**
- Boss 端 `navigator.webdriver` / UA 不伪造，完全用用户真实浏览器会话

### 7.2 事件真实性
- 定位按钮后先 `scrollIntoView({behavior: 'smooth', block: 'center'})`
- 发送事件序列替代 `.click()`：
  ```
  el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true,view:window}))
  sleep(200)
  el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true,view:window,button:0}))
  el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true,view:window,button:0}))
  el.dispatchEvent(new MouseEvent('click', {bubbles:true,cancelable:true,view:window,button:0}))
  ```

### 7.3 风控告警检测
每轮循环前调 `detectRiskControl()`：
- DOM 查询 `.captcha-wrap, [class*="verify"], [class*="risk-tip"], [class*="intercept"]` 任一可见 → halt
- 文案扫描 `document.body.innerText` 含「操作过于频繁」「请稍后再试」「账号异常」「人机验证」任一 → halt
- halt 策略：`_stopped=true` + `_running=false` + popup 弹红横幅「检测到 Boss 风控，已自动停止」+ 最后一个点过的候选人回调 record-greet success=false, error_msg='risk_control_detected'

### 7.4 熔断机制
- 单次运行连续 3 次「点了打招呼按钮但按钮文案未变」→ 视为 Boss 软拦截，halt
- 连续 5 次 evaluate_and_record 返非 `should_greet`（纯分低不算，算 error_no_competency/error_network）→ halt

### 7.5 小号隔离
`spec` 文档 warning 章节写：**禁止用招聘主账号跑 F3**，建议单独 HR 小号。R7 合规风险降级但未消除。

## 8. 数据模型改动

### 8.1 新字段

```sql
-- users 表
ALTER TABLE users ADD COLUMN daily_cap INTEGER DEFAULT 1000 NOT NULL;

-- jobs 表
ALTER TABLE jobs ADD COLUMN greet_threshold INTEGER DEFAULT 60 NOT NULL;

-- resumes 表
ALTER TABLE resumes ADD COLUMN boss_id VARCHAR(100) DEFAULT '' NOT NULL;
ALTER TABLE resumes ADD COLUMN greet_status VARCHAR(20) DEFAULT 'none' NOT NULL
  CHECK (greet_status IN ('none','pending_greet','greeted','failed','skipped'));
ALTER TABLE resumes ADD COLUMN greeted_at DATETIME;
CREATE UNIQUE INDEX IF NOT EXISTS ix_resumes_user_boss
  ON resumes(user_id, boss_id) WHERE boss_id != '';
```

### 8.2 Alembic 迁移
`migrations/versions/0010_recruit_bot_fields.py` revision `0010`，down_revision `0009`（当前最新 `0009_jobs_scoring_weights`）。SQLite ALTER TABLE 限制：CHECK 约束需 table rebuild（Alembic batch mode 处理）。

### 8.3 审计事件 f_stage 枚举新增
- `F3_evaluate`
- `F3_greet_sent`
- `F3_greet_failed`
- `F3_risk_detected`

## 9. 错误处理矩阵

| # | 场景 | 表现 | 处理 | 中断运行? |
|---|---|---|---|---|
| E1 | 后端不可达 | fetch timeout / network error | 当前候选人 mark `error_network`，log，跳过 | 否 |
| E2 | 后端 5xx | HTTP 500 | 同 E1 | 否 |
| E3 | JWT 过期 | HTTP 401 | halt + popup 弹 "登录过期" | 是 |
| E4 | DOM 抠取失败 | 关键字段 name/education 空 | mark `scrape_incomplete`，跳过 | 否 |
| E5 | 打招呼按钮找不到 | selector 返 null | 后端 record-greet success=false reason='button_not_found'，跳过 | 否 |
| E6 | 点了但 Boss 无反应 | 文案不变 + 无 dialog | 连续 3 次 → 熔断 halt | 连 3 次才中断 |
| E7 | 风控弹窗 | §7.3 规则命中 | halt + 警告横幅 | 是 |
| E8 | daily_cap 超限 | decision=blocked_daily_cap | popup 提示，halt | 是 |
| E9 | 选的 job 无 competency_model | decision=error_no_competency | popup 提示，halt | 是 |
| E10 | 岗位对齐失败 | 相似度 < 0.7 | popup 弹确认 | 用户选否则 halt |
| E11 | 候选人已历史打过 | decision=skipped_already_greeted | 记 log 不计 cap 继续 | 否 |
| E12 | 分数低于阈值 | decision=rejected_low_score | resume=rejected，继续 | 否 |
| E13 | HR 点暂停 | `_paused=true` | 当前完成后停下一个 | 是（可恢复） |
| E14 | Content script 未捕获异常 | unhandled exception | popup 红字 + halt | 是 |

**幂等与并发**：
- `evaluate_and_record` 幂等：同 (user_id, boss_id) 多次调用返相同 resume_id + 相同 decision
- `record_greet_sent` 幂等：`UPDATE ... WHERE greet_status != 'greeted'`
- 同一 HR 不得同时开两个 tab 跑 F3：`chrome.storage.recruitRunning=true` popup 启动前校验

## 10. 测试策略

### 10.1 后端单元 (`tests/modules/recruit_bot/test_service.py`)
11 个测试覆盖 upsert / threshold / daily_cap / already_greeted / record_greet / audit / per-user_isolation。

### 10.2 后端路由 (`tests/modules/recruit_bot/test_router.py`)
5 个测试覆盖 auth / foreign job 404 / 参数校验 / usage / cap。

### 10.3 后端集成 (`tests/modules/recruit_bot/test_integration.py`)
5 个测试端到端：should_greet / rejected / idempotent_evaluate / idempotent_greet / multi_user_cap。

### 10.4 前端 E2E 手工 checklist
content.js DOM 操作难写自动化测试（反检测 + DOM 依赖实时 Boss 页）。落为 9 项手工验证：

1. popup 打开，job 下拉有选项
2. 选 job → 配额显示"已打 N/1000"
3. 点"开始" → 推荐页有卡片即开跑
4. 跑 5 个后点页面暂停，验证暂停生效，再续跑
5. 跑到低于阈值的候选人：popup 显"X：分 45 低于 60，跳过"
6. 跑到已打过的：popup 显"Y：已打过招呼，跳过"
7. 人为制造风控（连续点 20+ 次），验证 halt + 红横幅
8. 跑到 cap 自动 halt + 提示
9. 跑完后 `resumes` 表有新行，`audit_events` 有 F3_* 行，`greet_status='greeted'` 行数 == 成功计数

### 10.5 性能基线
- 后端 evaluate_and_record P95 < 3s
- 前端单候选人总时长 P50 6-10s
- 100 人单次运行预计 10-17 分钟

### 10.6 测试总数
11（service） + 5（router） + 5（integration） = **21** 新增测试。合并前 `tests/ -q --ignore=tests/e2e` 期望 `~394 passed / 7 failed`（7 = M2 scheduling pydantic baseline）。

## 11. 配置

`.env` 新增（默认值即可）：
- `F3_DEFAULT_GREET_THRESHOLD=60` — 新建 job 默认值（可被 per-job 覆盖）
- `F3_DEFAULT_DAILY_CAP=1000` — 新建 user 默认 cap
- `F3_AI_PARSE_ENABLED=false` — Q7a 预留开关，MVP 不用

## 12. 风险与缓解

| ID | 风险 | 缓解 |
|---|---|---|
| R1 | Boss 推荐页 DOM 变动 | T1 抽 selector 到常量文件，未来改 selector 仅改一处；手工 E2E checklist 发现变动 |
| R2 | 反检测失效导致封号 | §7 全链路安全设计 + 小号隔离 + 熔断；**禁止主账号** |
| R3 | daily_cap 绕过（用户篡改 storage） | 后端 evaluate 返 blocked_daily_cap 为权威拒绝点，前端只是预提示 |
| R4 | greet_status 与 audit_events 不一致 | service.py 同事务内写两者；集成测试覆盖 |
| R5 | 推荐列表长度未知导致跑飞 | Q5b 无单次上限，但 daily_cap + 熔断兜底 |
| R6 | Boss 岗位名格式变（"全栈工程师_北京 400-500元/天" vs "全栈工程师"）导致 Q8 对齐误报 | 提取岗位名时 split `_` 取首段 + 去薪资括号后再比 |
| R7 | 合规 / 法律（降级但未消除） | 小号隔离警告 + daily_cap 1000 不触 Boss 商业级爬取线 + 审计链 WORM |

## 13. Definition of Done

1. 10.1/10.2/10.3 全通过（21 个新测试）
2. `pytest tests/ -q --ignore=tests/e2e` 预期 `~394 passed / 7 failed`（7 = M2 scheduling baseline）
3. 10.4 手工 E2E 9 项全过
4. 文档 CHANGELOG 记 F3 入项
5. User 手工验收

## 14. 不解决的问题（已知限制）

- 推荐列表滚动加载机制 T1 抽 selector 时确认后写回 spec（懒加载触底 vs 按钮加载 vs 固定长度）。默认实现按"容器 scroll 触底 → 等新卡片插入"处理，遇不同机制在 T1 调整
- F3 不识别 Boss 付费打招呼限制（若当日 Boss 免费打招呼 cap 打满，打招呼按钮仍显示但点击后 Boss 弹「开通套餐」dialog）→ 检测到该 dialog 视为风控熔断
- 已有 resume 从 Edge 扩展另一条路径（chat 页采集）建的，boss_id 可能空。F3 首次遇到该人 scrape 后回填 boss_id，但不保证稳定匹配；边界情况由 §9 幂等保证
- F3 不抓 modal 详情（自我介绍 / 工作经历描述 / 项目经验）— 见 §5.2；将来 `F3_AI_PARSE_ENABLED=true` 时作为扩展点开放

## 15. 开工顺序（建议 T 任务切分 — 后续 plan 阶段细化）

T0. 迁移 0010 + models 字段 + Pydantic schemas  
T1. **Live DOM 探查**（§5.2 LIST-only 已定路径）：抽 selector 常量集 — list card 容器 / 各字段 / 打招呼按钮 / 薪资 tag / skill tags 分类 / 风控告警元素 / 滚动加载触发器。2026-04-21 已 live 观察过，T1 是把观察变代码  
T2. service.py `upsert_resume_by_boss_id` + 测试  
T3. service.py `evaluate_and_record` + 测试  
T4. service.py `record_greet_sent` + `get_daily_usage` + 测试  
T5. router.py 4 端点 + 测试  
T6. content.js `scrapeRecommendCard` + `simulateHumanClick` + `detectRiskControl`  
T7. content.js `autoGreetRecommend` 主循环  
T8. popup.html + popup.js F3 section  
T9. 集成测试 + 性能基线测  
T10. 手工 E2E checklist + CHANGELOG + 提交

---

**End of design.**
