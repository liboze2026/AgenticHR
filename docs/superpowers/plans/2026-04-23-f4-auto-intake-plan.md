# F4 全自动 IM Intake 实施计划

关联设计文档：[2026-04-23-f4-auto-intake-redesign.md](../specs/2026-04-23-f4-auto-intake-redesign.md)

## 背景

原 F4 设计（2026-04-22）采用后端 APScheduler + Playwright 常驻浏览器，未实现。
F5/F6 已落地扩展驱动的人工触发采集（单人/批量），全链路验证通过。
本计划复用 F5/F6 基础实现 F4 愿景：扩展侧 `chrome.alarms` 定时唤醒 → 自动扫描 → 调用 F3.1 orchestrator 采集 → 终态上报。

## 命名统一

- F5 → F3.1（单人手动采集）
- F6 → F3.2（批量按 criteria 采集）
- F4 → 自动全量采集（本计划）

扩展 JS 函数前缀 `f5_*` → `intake_*`；元素 ID `#f5-intake-toast` → `#intake-toast`。

## 总体顺序（禁跳步）

1. 命名重构（P4-P7）——保证代码/文档术语一致，后续删除/新增有清晰靶点
2. 旧后端 daemon 代码删除（P8）——腾出命名空间给新实现
3. 扩展自动循环（P9）——F4 核心功能入口
4. 后端 F4_* 审计事件（P10）
5. 新端点 + 终态自动化（P11）
6. 端到端验证（P12）

每个 Phase 完成后必须跑"4步验证"（alembic / curl / 截图 / 4xx 列表），失败即修不跳过。

---

## Phase 4：文档命名 F5 → F3.1

### 目标
所有文档中 "F5" 字样统一改为 "F3.1"，"manual-intake"/"手动采集" 描述保留。

### Task 列表

- [ ] T4.1 重命名 `docs/superpowers/plans/2026-04-22-f5-manual-intake-plan.md` → `2026-04-22-f3.1-manual-intake-plan.md`（git mv），文件内 "F5" 全量替换 "F3.1"
- [ ] T4.2 重命名 `docs/f5-manual-intake-qa.md` → `docs/f3.1-manual-intake-qa.md`，内容同步替换
- [ ] T4.3 `CHANGELOG.md` 中 F5 段改为 F3.1（保留原日期）
- [ ] T4.4 `docs/superpowers/specs/` 下任何引用 F5 的 spec 同步更新（grep 扫描）
- [ ] T4.5 仓库全局 `grep -rn "F5\|f5_intake\|f5_manual"` 清零（测试/代码另 Phase 处理）

### 验收
- `grep -rn "F5" docs/` 仅命中非 intake 相关历史文字
- 文件名清单 git log 可追溯

---

## Phase 5：后端代码命名 F5 → F3.1

### 目标
后端代码、迁移注释、测试中 "F5" 字样统一。不改数据库表名/字段名（避免跨迁移风险）。

### Task 列表

- [ ] T5.1 `app/modules/im_intake/*.py` docstring/注释中 "F5" → "F3.1"
- [ ] T5.2 `migrations/versions/0012_*.py` docstring 顶部注释 "F5" → "F3.1"（不改 revision ID）
- [ ] T5.3 `app/modules/im_intake/slot_filler.py` 中 `f_stage="f5_intake"` 若存在 → `"intake"`（审计事件 stage 统一）
- [ ] T5.4 `tests/modules/im_intake/test_router_*.py` 中 "F5" 字样替换
- [ ] T5.5 `app/config.py` 相关设置项注释更新

### 验收
- `grep -rn "F5\|f5_" app/ tests/ migrations/` 清零（或仅剩已归档历史）
- `pytest tests/modules/im_intake/ -x` 全绿
- 4步验证：alembic upgrade head / curl /api/health 200 / 前端已改页面截图 / 4xx 列表

---

## Phase 6：扩展命名 f5_* → intake_*

### 目标
`edge_extension/` 下 JS 函数/变量 `f5_*` 前缀全改为 `intake_*`。

### Task 列表

- [ ] T6.1 `content.js` 39 处 `f5_*` 函数/变量替换（按 grep 清单）
- [ ] T6.2 元素 ID `#f5-intake-toast` → `#intake-toast`
- [ ] T6.3 `popup.js`/`background.js` 调用点同步
- [ ] T6.4 `manifest.json` 如有 f5 引用同步

### 验收
- `grep -rn "f5_\|f5-intake" edge_extension/` 清零
- Chrome 加载扩展无控制台报错
- Boss 直聘页手动触发单人采集功能正常（回归 F3.1）

---

## Phase 7：F6 → F3.2 命名

### Task 列表

- [ ] T7.1 `docs/superpowers/plans/2026-04-23-f6-batch-chat-collect-plan.md` → `2026-04-23-f3.2-batch-chat-collect-plan.md`
- [ ] T7.2 `CHANGELOG.md` F6 段 → F3.2
- [ ] T7.3 代码中若有 `F6` 字样注释同步
- [ ] T7.4 扩展 `batchCollectNew` 相关注释 F6 → F3.2

### 验收
- `grep -rn "F6" docs/ app/ edge_extension/` 清零
- F3.2 批量采集功能回归通过

---

## Phase 8：删除后端 Playwright F4 daemon

### 删除清单

- [ ] T8.1 `app/main.py` 行 35-72 F4 scheduler 启动块
- [ ] T8.2 `app/modules/im_intake/scheduler.py` 整个文件
- [ ] T8.3 `app/modules/im_intake/service.py` 中 `process_one()` 方法
- [ ] T8.4 `app/modules/im_intake/router.py` 中 `/scheduler/status`、`/scheduler/pause`、`/scheduler/resume`、`/scheduler/tick-now` 四个端点 + `_scheduler()` 辅助
- [ ] T8.5 `app/config.py` 删除 `f4_enabled`、`f4_scan_interval_min`、`f4_batch_cap`（保留 `f4_hard_max_asks`、`f4_pdf_timeout_hours`、`f4_soft_question_max`）
- [ ] T8.6 `tests/modules/im_intake/test_concurrent_lock.py` 删除
- [ ] T8.7 `tests/modules/im_intake/test_scheduler_lock.py` 删除
- [ ] T8.8 `tests/modules/im_intake/test_scheduler_disabled_by_default.py` 删除
- [ ] T8.9 `frontend/src/views/Intake.vue` 顶部 control-bar（调度器 UI）整块删除
- [ ] T8.10 `frontend/src/api/intake.js` 删除 `getSchedulerStatus`/`pauseScheduler`/`resumeScheduler`/`tickNow`
- [ ] T8.11 `app/adapters/boss/playwright_adapter.py` 若仅被 F4 daemon 使用 → 删除；若被其他模块用 → 保留
- [ ] T8.12 `requirements.txt` 如有仅为 daemon 用的 playwright/apscheduler → 评估删除

### 验收
- `grep -rn "IntakeScheduler\|process_one\|f4_enabled\|f4_batch_cap" .` 清零
- 后端启动日志无 F4 scheduler 相关行
- `pytest tests/` 全绿（除已删文件）
- Intake.vue 页面加载无报错，候选人列表/操作按钮仍正常
- 4步验证完整通过

---

## Phase 9：扩展 chrome.alarms 自动循环

### 目标
扩展 background.js 用 `chrome.alarms` 定时唤醒，注入 content.js 触发 `intake_autoScanTick`；自动扫描未完成候选人，挨个跳转到 Boss 聊天页复用 F3.1 orchestrator。

### Task 列表

- [ ] T9.1 `edge_extension/manifest.json` 加 `"alarms"` 权限（若无）
- [ ] T9.2 `background.js` 注册 `chrome.alarms.create("intake_autoscan", {periodInMinutes: 10})`，listener 打开/切换到 Boss 聊天页并注入 tick
- [ ] T9.3 `content.js` 新增 `intake_autoScanTick()`：调 `/api/intake/autoscan/rank` 取候选人列表 → 逐个跳转 + 运行 orchestrator
- [ ] T9.4 `popup.js` 新增"自动扫描"开关，写 `chrome.storage.local` 控制 alarm 启停
- [ ] T9.5 `popup.html` 加开关 UI
- [ ] T9.6 扩展侧 daily-cap 检查：每 tick 先调 `/api/intake/daily-cap`，超限则跳过
- [ ] T9.7 失败重试 + 指数退避逻辑（服务端 409/429 时延长 alarm 周期）

### 验收
- Chrome 扩展管理页无控制台错误
- popup 开关切换持久化（reload 扩展后保留状态）
- 开启后手工 chrome://extensions → Service Worker → trigger alarm 能看到 tick 日志
- Boss 直聘已登录状态下自动跳转到未完成候选人并触发 F3.1 orchestrator
- 4步验证通过

---

## Phase 10：后端 F4_* 审计事件

### 9 个 stage

`F4_autoscan_tick`、`F4_candidate_enter`、`F4_extract_history`、`F4_question_sent`、`F4_pdf_requested`、`F4_pdf_received`、`F4_completed`、`F4_pending_human`、`F4_abandoned`

### Task 列表

- [ ] T10.1 在 `app/modules/im_intake/service.py` `analyze_chat`、`record_asked`、`apply_terminal` 各关键分支插入 `audit_events` 写入（复用现有 audit helper）
- [ ] T10.2 `/collect-chat` 端点入口写 `F4_candidate_enter`（首次）
- [ ] T10.3 `/autoscan/tick-stats` 端点写 `F4_autoscan_tick`
- [ ] T10.4 终态转移（complete/pending_human/abandoned）写对应事件
- [ ] T10.5 单测：`tests/modules/im_intake/test_audit_events.py` 覆盖 9 个 stage

### 验收
- `SELECT stage, count(*) FROM audit_events WHERE stage LIKE 'F4_%' GROUP BY stage` 9 行
- pytest 全绿
- 4步验证

---

## Phase 11：新端点 + 终态自动化

### Task 列表

- [ ] T11.1 `GET /api/intake/daily-cap` → 返回 `{used: N, max: M, remaining: K}`（按 user_id 按天统计 F4_autoscan_tick）
- [ ] T11.2 `GET /api/intake/autoscan/rank?limit=20` → 按优先级返回下一批待扫描候选人 `[{candidate_id, boss_id, reason}]`
    - 优先级：awaiting_reply 超时 > collecting 有待问题 > pending_human（跳过）
- [ ] T11.3 `POST /api/intake/autoscan/tick-stats` → 扩展上报本轮 tick 统计 `{processed, skipped, errors}`；写 audit
- [ ] T11.4 service 加 `auto_flag_pending_human(c)`：N 次未响应/PDF 超时 → 转 `pending_human` + 事件
- [ ] T11.5 service 加 `auto_abandon(c)`：超过 `f4_pdf_timeout_hours` + 无进展 → 转 `abandoned` + 事件
- [ ] T11.6 后台任务 / 端点触发（每次 tick 时调用）上述两个终态判定
- [ ] T11.7 schemas 加 `DailyCapOut`、`AutoScanRankOut`、`TickStatsIn`
- [ ] T11.8 router 3 个端点挂到 `/api/intake`
- [ ] T11.9 Intake.vue 加"每日剩余额度"显示（替换删掉的 scheduler 面板）

### 验收
- `curl /api/intake/daily-cap` 返回 200 + 合法 JSON
- `curl /api/intake/autoscan/rank` 返回 200 + 非空列表（有候选人时）
- pytest 覆盖三端点
- 前端 Intake.vue 显示新的"剩余额度"卡片
- 4步验证

---

## Phase 12：端到端验证

### 必须产出

- [ ] T12.1 `alembic upgrade head` 输出（应为 "Already at 0016" 或新加的 F4 迁移 ID）
- [ ] T12.2 `curl http://localhost:8000/api/health` → 200
- [ ] T12.3 `curl http://localhost:8000/api/intake/daily-cap` → 200
- [ ] T12.4 `curl http://localhost:8000/api/intake/autoscan/rank` → 200
- [ ] T12.5 前端 `pnpm dev` + 浏览 `/intake` 截图
- [ ] T12.6 浏览 Boss 直聘页截图（扩展注入 intake_autoScanTick 日志）
- [ ] T12.7 Chrome DevTools Network 面板所有 4xx/5xx 清单（逐个定位修复）
- [ ] T12.8 扩展开启自动扫描 → 等 1 轮 tick → 验证候选人状态推进
- [ ] T12.9 手动触发 `/api/intake/autoscan/tick-stats` 写入 → 查 audit_events 验证

### 完成标准
所有 T12.x 截图/日志贴入本文档末尾，4xx/5xx 全部解释或修复，任何一项失败回退到对应 Phase 修复。

---

## 风险清单

| 风险 | 缓解 |
|-----|-----|
| Boss 直聘改版破坏 DOM 选择器 | 选择器集中在 content.js 顶部常量，改版时一处改 |
| chrome.alarms 最小周期 1 分钟 | 设计周期 10 分钟留缓冲，不做秒级循环 |
| 候选人状态死循环（tick 反复扫同一人） | service 写 `last_autoscan_at` 冷却期，rank 端点跳过冷却中 |
| daily-cap 统计误差 | audit_events 为准，`F4_autoscan_tick` 一次 tick 写一次（非 per-candidate） |
| 删除 playwright 依赖影响其他模块 | T8.11 先 grep 确认唯一使用方再删 |

## 不做的事

- 不恢复后端 Playwright 常驻（F4 原设计）
- 不做跨用户共享候选池
- 不做 Boss 以外平台（保持 F3.1/F3.2/F4 Boss 专用）
- 不做扩展端 LLM 调用（继续后端集中调用）
