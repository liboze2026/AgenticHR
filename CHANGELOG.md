# Changelog

## [Unreleased] — 2026-04-22

### Added — F3.1 (原 F5): 单人手动采集模式
- 新表 `intake_candidates` 专装采集中候选人；`resumes` 表通过前端过滤 `intake_status='complete'` 展示简历库（T12 F3 迁移因与 F2 评分器耦合而取消，改为前端过滤策略）
- `POST /api/intake/collect-chat` — 插件提交聊天快照，后端解析 slot、跑 decide_next_action 返回 NextAction
- `POST /api/intake/candidates/{id}/start-conversation` — 返回 Boss 聊天 deep link（带 `intake_candidate_id` query）
- `POST /api/intake/candidates/{id}/ack-sent` — 插件回报已发送
- `promote_to_resume()` 把信息齐全候选人搬到 resumes 表
- 插件 `chat_scrape.js` 纯 DOM 解析器 + `content.js` 自动化助手 (`intake_typeAndSendChatMessage` / `intake_clickRequestResumeButton` / `intake_checkPdfReceived`)
- 插件 orchestrator：检测 URL 参数 `intake_candidate_id` 自动接管聊天页 → collect-chat → 按 NextAction 发消息/点按钮 → ack-sent
- 插件 popup 按钮 "采集当前聊天候选人"（测试入口）
- `/intake` 行加 "开始沟通" 按钮 → `window.open(deep_link)` → 插件接管
- `/resumes` 加语义说明横幅 + 前端过滤 `intake_status='complete'`
- `ResumeResponse` schema 暴露 `intake_status` 字段

### Changed
- `IntakeService.process_one` 拆分为 `analyze_chat` + `record_asked` + `apply_terminal`，便于插件/调度器共用
- `decide_next_action` 抽成纯函数（7 个分支：send_hard / request_pdf / wait_pdf / send_soft / complete / mark_pending_human / abandon）
- `intake_slots.resume_id` → `intake_slots.candidate_id`（迁移 0012 自动搬数据）
- `/api/intake/candidates` 列表/详情从 `Resume` 切换到 `IntakeCandidate`
- 路径参数 `/candidates/{resume_id}/abandon` → `/candidates/{candidate_id}/abandon`（同样适用于 force-complete）
- F4 APScheduler 默认关闭（`F4_ENABLED=false`），代码保留便于日后启用
- Edge 扩展 manifest 匹配扩展到 `zhipin.com/web/chat/*`

### Cancelled
- T12（F3 写 IntakeCandidate）：F3 的 `evaluate_and_record` 与 F2 `MatchingService.score_pair(resume_id, job_id)` 深度耦合，迁移要求跨模块改造。改为保留 F3 现状 + 前端 `intake_status='complete'` 过滤的策略，以更低成本达成"简历库只显示采集完成候选人"语义。

### Test baseline
- Before F3.1: 414 passed / 7 failed (F4 main baseline)
- After F3.1: 105 passed in im_intake (0 fail, 1 skipped for plugin e2e); resume/recruit_bot suites unchanged

## [Unreleased] — 2026-04-21

### Added — F4: Boss IM 候选人信息收集
- 后端 Playwright 守护进程 + APScheduler 15min 定时扫描 chat/index
- `intake_slots` 副表 + `Resume.intake_status` 字段，slot 级 asked/answered 时间戳
- SlotFiller (regex 优先 + LLM 兜底)、QuestionGenerator (硬性模板 + 软性 LLM)、PdfCollector
- IntakeService 完整流水线：硬性 3 次问不到 → pending_human；PDF 72h 不到 → abandoned；齐全 → complete
- REST API `/api/intake/*` + 前端 `Intake.vue` 列表 + slot 详情抽屉
- 与 F3 共享 `BossAdapter` 单例 + asyncio.Lock，F3 优先
- 新增 env: `F4_ENABLED`, `F4_SCAN_INTERVAL_MIN`, `F4_BATCH_CAP`, `F4_HARD_MAX_ASKS`, `F4_PDF_TIMEOUT_HOURS`, `F4_SOFT_QUESTION_MAX`, `AI_MODEL_INTAKE`

### Added (F3 — Boss 推荐牛人自动打招呼)
- 新增 `app/modules/recruit_bot/` 模块（schemas/service/router）
- 4 个端点：`POST /api/recruit/evaluate_and_record`、`POST /api/recruit/record-greet`、`GET /api/recruit/daily-usage`、`PUT /api/recruit/daily-cap`
- Edge 扩展 popup 加 F3 section（岗位下拉 + 配额 + 开始按钮）
- `content.js` 加 `autoGreetRecommend()` 主循环 + 反检测工具（`simulateHumanClick` / `detectRiskControl` / `scrapeRecommendCard`）
- 反检测硬约束：随机 2-5s 间隔、每 10 个长停 3-6s、事件序列（mouseover→mousedown→mouseup→click）、风控 DOM/文案扫描 halt、连续 3 次按钮无反应熔断
- 53 个新测试（schemas 7 + migration 5 + upsert 6 + evaluate 9 + record_greet 6 + daily_usage 4 + router 11 + integration 5）

### Changed
- `users` 表加 `daily_cap`（默认 1000）
- `jobs` 表加 `greet_threshold`（默认 60）
- `resumes` 表加 `boss_id` / `greet_status` / `greeted_at`，加 `UNIQUE(user_id, boss_id)` 部分索引
- Alembic 迁移 `0010_f3_recruit_bot_fields`

### Notes
- **禁止用招聘主账号跑 F3**，用 HR 小号（合规 R7）
- 话术非 LLM 生成，用 Boss 默认文案；无 HITL
- LIST-only 抓取策略（spec §5.2）；模态详情抓取留给 `F3_AI_PARSE_ENABLED=true` 未来开启
- 本地 dev DB 需要 `alembic upgrade head` 一次以同步新字段（在此 branch 首次 checkout 后）

### Test baseline
- Before F3: 373 passed / 7 failed (M2 scheduling pydantic baseline)
- After F3: 414 passed / 7 failed / 12 errors (errors pre-existing screening fixture issues, unrelated)
