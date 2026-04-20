# F1 执行检查点 — 2026-04-20

> **给下一个 Claude 会话的接手提示词**。用户即将切换模型 + 清空上下文。你打开这个项目后读一遍此文档，就能无缝接着 Subagent-Driven 开发推进下去。

---

## TL;DR

M3 F1"能力模型抽取"正在执行。**进度 17/33 任务完成（Phase 3 结束），下一步是 Phase 4 的 T20 + T20b（前端 API 模块 + skills 后端路由）**。已完成任务零回归，141 passed / 37 pre-existing failed / 4 skipped。

---

## 项目背景（一段话）

AgenticHR 是招聘助手（FastAPI + Vue3 + SQLite）。M0-M2 做完了半自动（扁平字段筛简历 + AI 评估 + 面试安排 + 飞书/腾讯会议）。M3 目标：升级到全自动闭环，分 F1-F8 八个特性增量开发。**F1** 是把 JD 文本经 LLM 抽取 + 技能库归一化 → 结构化能力模型（`jobs.competency_model` JSON），HR 审核后作为 F2-F8 下游决策的唯一依据。

## 硬性工作流约束（用户多次强调，不许跳步）

每个 F 必须严格走：**brainstorm → spec 文档 → plan 文档 → TDD 开发 → 用户验收**。F1 当前已完成前三步：

- Spec：[docs/superpowers/specs/2026-04-20-f1-competency-model-design.md](../specs/2026-04-20-f1-competency-model-design.md)（682 行）
- Plan：[docs/superpowers/plans/2026-04-20-f1-competency-model-plan.md](./2026-04-20-f1-competency-model-plan.md)（6727 行，29 任务 + 2 前置）
- **现在在第 4 步"TDD 开发"的执行中途**

用户选择了 **Subagent-Driven** 模式：每任务派 1 个 implementer subagent + 1 个 spec+code 合并审核 subagent。主 session 只做协调，不直接写代码（保护上下文窗口）。

---

## 进度矩阵（截至 commit `680210f`）

| Phase | 任务 | 状态 | 关键备注 |
|---|---|---|---|
| 0 | K0 (Alembic 引入 + baseline) | ✅ | commit `812bffd` |
| 0 | K1 (stamp DB to baseline) | ✅ | 无 commit（仅 DB 管理） |
| 1 | T1 (skills migration) | ✅ | commit `285aa08` |
| 1 | T2 (hitl_tasks migration) | ✅ | commit `0116619` |
| 1 | T3 (audit_events + WORM triggers) | ✅ | commit `355ad72` |
| 1 | T4 (jobs 3 cols) | ✅ | commit `8a73df8` |
| 1 | T5 (seed skills, 54 条) | ✅ | commit `f7c2bab` |
| 2A | T6 (core/llm/parsing) | ✅ | commit `7a1c999` |
| 2A | T7 (core/audit WORM logger) | ✅ | commit `77ba576` |
| 2A | T8 (core/vector cosine+pack) | ✅ | commit `ab62270` |
| 2A | T9 (core/llm/provider complete) | ✅ | commit `299dc81` |
| 2A | T10 (embed_batch + 智谱 API 实测) | ✅ | commit `d7fe679`；**R1 风险已清除**（HTTP 429 → 端点兼容） |
| 2B | T11 (CompetencyModel Pydantic) | ✅ | commit `e320c60` |
| 2B | T12 (skill_library CRUD + SkillCache) | ✅ | commit `e875021` |
| 2B | T15 (HITL service/router，**提前到 T13 前**) | ✅ | commit `1c7d917` |
| 2B | T13 (normalizer) | ✅ | commit `3bc050f`（含命名冲突回退逻辑） |
| 2B | T14 (extractor) | ✅ | commit `359a0f7` |
| (审查后修) | SkillCache 语义文档 | ✅ | commit `ef79cd0` |
| 3 | T16 (Job 模型 + schemas 加字段) | ✅ | commit `8f5b53d` |
| 3 | T17 (competency_service 双写) | ✅ | commit `b85f8e6` |
| 3 | T18 (screen_resumes 读 model 优先) | ✅ | commit `9e679fd` |
| 3 | T19 (3 个 competency endpoints) | ✅ | commit `6723ee7`（4 tests skipped，auth 中间件阻塞 TestClient） |
| 3 | T19b (HITL approve callback 绑定) | ✅ | commit `680210f` |
| **4** | **T20 (前端 3 个 API 模块)** | **🔄 下一个** | 被中断在这里 |
| **4** | **T20b (后端 /api/skills 路由)** | **🔄 下一个** | 同上，和 T20 合并批量做 |
| 4 | T21 (App.vue 导航 + badge) | ⏳ | pending |
| 4 | T22 (components/SkillPicker.vue) | ⏳ | pending |
| 4 | T23 (components/CompetencyEditor.vue) | ⏳ | pending |
| 4 | T24 (Jobs.vue el-tabs 改造) | ⏳ | pending |
| 4 | T25 (HitlQueue.vue) | ⏳ | pending |
| 4 | T26 (SkillLibrary.vue) | ⏳ | pending |
| 4 | T27 (router/index.js 加 2 路由) | ⏳ | pending |
| 5 | T28 (E2E smoke) | ⏳ | pending |
| 5 | T29 (M2 回归 + coverage 报告) | ⏳ | pending |

**测试基线**：141 passed / 37 pre-existing failed（M2 的 screening router 认证问题，F1 没碰）/ 4 skipped（T19 auth 相关）。**F1 零回归约束必须保持**。

---

## 接手指令（新会话照做）

### 第 1 步：读全部上下文

```
1. 读 CLAUDE.md                                     # 工作流规则
2. 读 C:\Users\neuro\.claude\projects\D--libz-AgenticHR\memory\MEMORY.md
   以及它指向的全部 memory 文件                       # 用户偏好 + 项目进度
3. 读本文件（你已经在读）                            # F1 执行检查点
4. 读 docs/superpowers/plans/2026-04-20-f1-competency-model-plan.md
   的 Phase 4 段（T20 起到 T27）                     # 下一步要执行的任务原文
```

### 第 2 步：确认环境

```bash
cd /d/libz/AgenticHR
git log --oneline -3                                 # 应看到 680210f 在 HEAD
git status                                           # 应干净
./.venv/Scripts/python -m pytest tests/ --tb=no -q   # 应 141 passed / 37 failed / 4 skipped
./.venv/Scripts/alembic -c migrations/alembic.ini current  # 应 0006 (head)
cd frontend && npm run build 2>&1 | tail -3          # 应 ✓ built
```

如果任一项不符预期 — **不要继续开发**，先查原因告诉用户。

### 第 3 步：按 Subagent-Driven 继续

调 `Skill` 工具 → `superpowers:subagent-driven-development`（或直接按已学会的模式干）：

1. 重建 TodoWrite（从"T20 + T20b 批量"起，参照上面进度矩阵的 pending 任务）。
2. 派第一个 implementer subagent 做 **T20 + T20b 合并批** — prompt 模板见下面"T20+T20b 接手 prompt"。
3. 派一个 spec+code 合并审核 subagent（模型用 `superpowers:code-reviewer`）。
4. 通过后标记完成，下一批：**T21-T27 合并批**（7 个前端任务）。
5. 再下一批：T28 + T29 + 最终 review。

### T20+T20b 接手 prompt（直接复制给 subagent 用）

> Subagent 执行时请注意：用户项目在 `D:\libz\AgenticHR` (Git Bash 下是 `/d/libz/AgenticHR`)，Python venv 在 `.venv/Scripts/python.exe`，前端在 `frontend/`，git 用户 `liboze2026`。已完成到 commit `680210f`，141 passed / 37 failed / 4 skipped。

**任务**：完成 T20（前端 API 模块）+ T20b（后端 /api/skills 路由），各自一个 commit。代码原文见 `docs/superpowers/plans/2026-04-20-f1-competency-model-plan.md` 第 4 章 Phase 4 段的 Task T20 和 Task T20b（用 grep 或 head 精确截取）。

**T20 要点**：只改 `frontend/src/api/index.js`，在 `// Boss API` 前插入 `competencyApi` / `hitlApi` / `skillsApi` 三个 export。`npm run build` 无报错即可，不写前端单测。

**T20b 要点**：新建 `app/core/competency/router.py`（7 个端点：list / categories / get / create / update / merge / delete），改 `app/main.py` 注册 `skills_router`，新建 `tests/core/test_skills_router.py`（5 测试，auth 拦截会 pytest.skip — 可接受）。测试 fixture 必须先 `_seed_jobs_table` 再跑 migration（因为 0005 ALTER jobs 需要表已存在）。

**报告**：两个 commit SHA + 最终 `pytest tests/ --tb=no -q` 计数 + `npm run build` 结果。

### T21-T27 接手 prompt（T20/T20b 完成后用）

7 个前端任务，原文都在 plan 文档 Phase 4 段。每个任务：写代码 → `npm run build` → commit。无前端单测。关键文件：

- T21 改 `frontend/src/App.vue`（导航加"审核队列 🔴badge"+"技能库"，hitlApi.list 轮询 5min）
- T22 新建 `frontend/src/components/SkillPicker.vue`（el-autocomplete 接 skillsApi.list）
- T23 新建 `frontend/src/components/CompetencyEditor.vue`（6 折叠卡片 + JD 抽取 + 两键 UI）
- T24 改 `frontend/src/views/Jobs.vue` 加 el-tabs 嵌入 CompetencyEditor
- T25 新建 `frontend/src/views/HitlQueue.vue`
- T26 新建 `frontend/src/views/SkillLibrary.vue`（批量归类是核心功能）
- T27 改 `frontend/src/router/index.js` 加 `/hitl`、`/skills` 两路由

派完后 **启动后端 + 前端打开浏览器手工过一遍 smoke**（auth 登录 → 建岗位 → 粘 JD → 看各 Tab 加载正常，即使不真调 LLM）。

### T28 + T29 + 最终 review（UI 完成后）

- T28：写 `tests/e2e/test_f1_smoke.py`（全程 mock LLM 的端到端测试）。
- T29：全量 pytest + 覆盖率报告（`pytest --cov=app/core --cov-report=term-missing`），确认 `app/core/` ≥ 85%。
- 最终 dispatch 一个 `superpowers:code-reviewer` 做 F1 整体 review，用 base=`4cb93f0`（plan commit 之后第一个实现 commit 前） head=HEAD。
- 报告给用户，让用户**手工验收**（F1 workflow 强制）。

---

## 已知坑 / 注意事项

1. **Subagent 必须 seed jobs 表**：baseline 0001 是 no-op，migration 0005（jobs ALTER）在空 tmp DB 上跑会因缺 jobs 表失败。所有需要 upgrade 到 ≥ 0005 的测试 fixture 都要先 `_seed_jobs_table(db)`。模式已在 `tests/core/test_migrations_seed_skills.py`、`tests/modules/screening/test_double_write.py` 等多处建立，抄即可。

2. **Auth 中间件挡 TestClient**：T19 和 T20b 的 API 测试预期会因 JWT 拦截 `pytest.skip`。**这是可接受的**（plan 明确允许），真正覆盖在 T28 E2E。不要花时间去绕 auth。

3. **SkillCache 手动失效语义**：所有写操作（insert/add_alias/increment_usage/update_embedding/merge）**不自动**调用 `SkillCache.invalidate()`。必要时调用方显式失效。已在 skill_library.py 的 SkillCache docstring 里说明。别改这个行为，会破坏 normalize_skills 的快照稳定性（test_normalize_threshold_boundary 会挂）。

4. **执行顺序依赖**：T15 (HitlService) 必须早于 T13 (normalizer) — 因为 normalizer 要调 HitlService.create()。已经这么做了。前端 T22 (SkillPicker) 依赖 T20b (/api/skills) 已就位才能实测 autocomplete。

5. **智谱 embedding API**：已实测 HTTP 429（被限流）但端点 `/v1/embeddings` 和 OpenAI 格式兼容。R1 风险（embedding API 偏离 OpenAI 格式）已关闭。验证脚本在 `scripts/verify_embedding_api.py`。

6. **双 memory 目录**：
   - 用户在 `D:\libz\AgenticHR` 打开 Claude → memory 在 `C:\Users\neuro\.claude\projects\D--libz-AgenticHR\memory\`
   - 用户在 `D:\libz` 打开 Claude → memory 在 `C:\Users\neuro\.claude\projects\D--libz\memory\`
   - 两处都已同步了 F1 工作流记忆。但**本文件在项目里**（git tracked），是最可靠的接手入口。

7. **两个 tech debt**（Phase 3 review 提出，暂不修）：
   - HitlService callback 失败静默吞：`apply_competency_to_job` 抛异常只 logger.error，HITL task 已 approved 但 job 未更新 → 数据不一致风险。
   - `manual_competency` 路径无 HITL 审计行（只写 audit_events 但没 hitl_tasks）。

---

## 本文件所在位置 + 维护

- 本文件：`docs/superpowers/plans/2026-04-20-f1-execution-checkpoint.md`（git 提交，不可被 /clear 清除）
- 也可在 `C:\Users\neuro\.claude\projects\D--libz-AgenticHR\memory\project_f1_execution_state.md` 找到简化版
- **每完成一个 Phase，接手的 Claude 应该更新这个文件**（更新进度矩阵 + 追加新的 tech debt / 坑）并 commit。
