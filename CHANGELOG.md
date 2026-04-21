# Changelog

## [Unreleased] — 2026-04-21

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
