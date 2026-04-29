# 2026-04-29 设计文档：candidate / resume 双表统一

## 0. 背景

当前 `IntakeCandidate` 与 `Resume` 双表共存，承担"候选人身份 + 简历档案"两个职责，但入口分裂、关系松散：

| 入口 | 写 IntakeCandidate | 写 Resume |
|---|---|---|
| IM 聊天采集（主线） | ✅ | promote 后 ✅ |
| F3 自动打招呼 | ❌ | ✅ 直写 |
| 手动上传 PDF | ❌ | ✅ 直写 |

**问题集中在三点**：
1. **简历库孤儿**：前端简历库 list 已迁移读 `IntakeCandidate`（spec 0420 PR4），但 F3 + 手动上传写入的 Resume 行无对应 IntakeCandidate → 看不见。
2. **跨表反查**：`status` / `reject_reason` 仅在 Resume，IntakeCandidate 渲染要走 `promoted_resume_id` 反查 → N+1。
3. **DB 层无 1:1 约束**：`promoted_resume_id` 可重复指、Resume 可孤儿，靠应用层维护，长期会脏。

## 1. 目标

最小改动让数据流单一方向化，所有候选人入口统一走 `IntakeCandidate → promote → Resume`，并在 DB 层强制 1:1。

**非目标**：
- 不重命名 `Interview.resume_id` / `MatchingResult.resume_id` FK
- 不删除 Resume 表
- 不挪 `chat_snapshot` 大字段
- 不改 SlotFiller 抽取逻辑
- 不动 outbox 调度

## 2. 设计

### 三阶段、互不依赖、可独立回滚

#### 阶段 A — 加列 + 渲染层去反查（最低风险）

**Migration 0022**：
```sql
-- IntakeCandidate 加决策字段
ALTER TABLE intake_candidates ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending';
ALTER TABLE intake_candidates ADD COLUMN reject_reason VARCHAR(200) NOT NULL DEFAULT '';

-- 从 promoted Resume 回填
UPDATE intake_candidates
SET status = COALESCE(
    (SELECT r.status FROM resumes r WHERE r.id = intake_candidates.promoted_resume_id),
    CASE intake_candidates.intake_status
        WHEN 'complete'   THEN 'passed'
        WHEN 'abandoned'  THEN 'rejected'
        WHEN 'timed_out'  THEN 'rejected'
        ELSE 'pending'
    END
),
reject_reason = COALESCE(
    (SELECT r.reject_reason FROM resumes r WHERE r.id = intake_candidates.promoted_resume_id),
    ''
);
```

**渲染层改动**：
- `intake_view_service.candidate_to_resume_dict`：直接读 `c.status` / `c.reject_reason`，删除反查 `Resume` 的逻辑
- `promote_to_resume`：promote 时把 candidate.status 同步写到 Resume.status（双写过渡期）
- 任何写 candidate.status / reject_reason 的地方（如 `update_resume` 路径），同步写 Resume（向后兼容）

**测试**：
- T-A-1：渲染时不再触发 Resume 查询
- T-A-2：candidate.status 与 Resume.status 永远一致（写入路径任意）
- T-A-3：abandoned/timed_out 的 candidate 在简历库展示为 rejected

#### 阶段 B — 入口收敛

**手动上传 `/api/resumes/upload`**：
```python
def upload_pdf_resume(file, candidate_*, ...):
    # 1. 解析 PDF + 落盘
    file_path = save_pdf(file)
    raw_text = parse_pdf(file_path)

    # 2. ensure_candidate（boss_id 空时用 surrogate_key = sha256(file)）
    surrogate = candidate_boss_id or f"manual_{sha256(file_bytes)[:16]}"
    candidate = ensure_candidate_for_manual_upload(
        db, user_id=user_id, boss_id=surrogate,
        name=candidate_name, source="manual_upload",
    )

    # 3. 写 candidate 字段 + 三 hard slot 兜底
    candidate.pdf_path = file_path
    candidate.raw_text = raw_text
    fill_slots_from_page_info(db, candidate, page_info)

    # 4. promote → Resume
    if all_hard_slots_filled(candidate) and candidate.pdf_path:
        promote_to_resume(db, candidate, user_id=user_id)

    return _target_to_response_dict(candidate)
```

**F3 boss_automation / recruit_bot greet 路径**：
```python
def auto_greet(boss_id, ...):
    candidate = ensure_candidate(db, user_id, boss_id, ...)
    candidate.greet_status = "greeted"
    candidate.greeted_at = now()
    # 不再直接写 Resume.greet_status
```

**Resume.greet_status 双写过渡**：在 `ensure_candidate` 后若已存在 promoted Resume，同步写 Resume.greet_status；老查询路径仍能用。后续清理。

**测试**：
- T-B-1：手动上传后 IntakeCandidate 行存在
- T-B-2：手动上传 + 三槽齐 → 同步 promote 出 Resume
- T-B-3：手动上传 boss_id 为空时用 surrogate_key 去重，重复上传不重复建 candidate
- T-B-4：F3 greet 后 IntakeCandidate.greet_status = greeted
- T-B-5：简历库 list 包含三类入口的所有候选人

#### 阶段 C — DB 强制 1:1 约束

**Migration 0023**：
```sql
-- 1:1 锁 1：每个 Resume 最多被一个 candidate promote
CREATE UNIQUE INDEX uniq_intake_candidates_promoted_resume_id
  ON intake_candidates(promoted_resume_id)
  WHERE promoted_resume_id IS NOT NULL;

-- 1:1 锁 2：反向键
ALTER TABLE resumes ADD COLUMN intake_candidate_id INTEGER
  REFERENCES intake_candidates(id) ON DELETE SET NULL;

-- 回填
UPDATE resumes
SET intake_candidate_id = (
  SELECT c.id FROM intake_candidates c
  WHERE c.promoted_resume_id = resumes.id
);

-- 锁 2 唯一索引
CREATE UNIQUE INDEX uniq_resumes_intake_candidate_id
  ON resumes(intake_candidate_id)
  WHERE intake_candidate_id IS NOT NULL;
```

**前置 sanity check 脚本** `scripts/check_candidate_resume_invariants.py`：
- 检查 `promoted_resume_id` 是否有重复
- 检查孤儿 Resume（无对应 candidate）数量
- 阻塞 migration 直到清理完毕

**应用层**：
- `promote_to_resume` 同时维护 `Resume.intake_candidate_id = candidate.id`
- 删除 candidate 时不级联删 Resume（ON DELETE SET NULL），避免误删档案

**测试**：
- T-C-1：尝试两个 candidate promote 同一 Resume → DB 抛 IntegrityError
- T-C-2：双向查询（candidate → resume / resume → candidate）都 O(1)
- T-C-3：sanity check 脚本能识别脏数据

## 3. 数据流图（落地后）

```
┌──── 三个入口 ──────────────────────────────┐
│ IM 聊天 (扩展)  /  F3 自动招呼  /  手动上传 │
└────────────────┬──────────────────────────┘
                 ▼ ensure_candidate (boss_id or surrogate)
        ┌────────────────────────┐
        │  IntakeCandidate       │
        │  - 唯一身份 (user, key)│
        │  - 状态机 intake_status│
        │  - 决策 status/reject  │
        │  - chat_snapshot/slots │
        └────────────┬───────────┘
                     ▼ promote_to_resume (三槽齐 + PDF)
        ┌────────────────────────┐
        │  Resume                │
        │  - PDF 持久化           │
        │  - AI 评分              │
        │  - Interview FK 中心    │
        │  - intake_candidate_id ↗│
        │       (反向 1:1)        │
        └────────────────────────┘
```

## 4. 风险面

| 风险 | 缓解 |
|---|---|
| 手动上传无 boss_id 怎么去重 | `surrogate_key = "manual_" + sha256(file)[:16]` 入 `boss_id` 字段，user_id+boss_id 唯一索引天然 dedup |
| F3 历史 Resume 无 IntakeCandidate | 阶段 C migration 前跑 backfill 脚本（参考已有 0021） |
| AI worker 仍读 Resume.ai_parsed | 不动 worker，promote 时把 candidate 字段同步给 Resume；阶段 B 不影响 AI 链路 |
| 阶段 B 双写期 status 不一致 | promote_to_resume 是单点，强制一致；测试覆盖 |
| migration 失败 | 自动备份 `data/recruitment.db.bak.YYYYMMDD_HHMMSS`，每阶段独立 alembic revision，可单独 downgrade |
| Interview.resume_id 老链路 | promote_to_resume 保证有 Resume 行，FK 永远有效 |

## 5. 测试策略

### 单元测试新增
- `tests/modules/im_intake/test_promote_invariants.py`：1:1 约束、孤儿检查、双向查询
- `tests/modules/resume/test_intake_view_no_crosstable.py`：渲染层 SQL trace 不查 Resume
- `tests/modules/resume/test_status_dual_write.py`：status 双写一致性
- `tests/integration/test_resume_upload_via_candidate.py`：手动上传走 candidate
- `tests/integration/test_f3_greet_via_candidate.py`：F3 greet 走 candidate

### 全量
- `pytest tests/ -v`（基线 734 passed, 4 skipped）
- 阶段切换前后跑全量、贴输出

### E2E（每阶段后）
- 起 backend + frontend
- 手动上传 PDF → 简历库可见
- F3 自动招呼后简历库可见
- 状态显示正确（pending / passed / rejected）

## 6. 回滚预案

| 阶段 | 回滚 |
|---|---|
| 阶段 A | `alembic downgrade -1` 删除两列 + `git revert` 渲染层改动 |
| 阶段 B | `git revert` 入口改动；老 Resume 行保留不影响读 |
| 阶段 C | `alembic downgrade -1` 删除唯一索引 + `intake_candidate_id` 列 |

每阶段独立 commit，回滚不影响其他阶段。

## 7. 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 主表方向 | IntakeCandidate 主，Resume 持久化 + FK 中心 | Resume FK 改名成本爆炸；candidate 状态机更丰富 |
| status 双写 vs 只写 candidate | 阶段 A/B 期双写，阶段 C 后只写 candidate | 平稳过渡；老查询 Resume.status 路径有时间迁移 |
| 手动上传 surrogate | sha256(file)[:16] | 同文件重复上传天然去重；boss_id 字段已是 String(64) 容纳 |
| 1:1 约束时机 | 最后阶段 | 前两阶段稳定后才上锁，避免 migration 中途暴露脏数据炸库 |
| migration backup | 自动 .db.bak | 与 0428 spec 一致风格，可整体还原 |
| AI 字段 | 不挪 | 写入路径已稳定（_ai_parse_worker），双写复杂度高，收益低 |

## 8. 不在本次范围

- 不淘汰 Resume 表
- 不重命名 Resume.* FK
- 不优化 AI worker 写入路径
- 不动 chat_snapshot 存储
- 不改 outbox / scheduler

## 9. 落地节奏

| 周次 | 阶段 | 验收 |
|---|---|---|
| W1 | 阶段 A 实现 + 测试 | 全量绿；E2E 简历库渲染正常 |
| W2 | 阶段 B 实现 + 测试 | 三入口都建 candidate；简历库孤儿消失 |
| W3 | 阶段 C 实现 + 测试 | DB 约束生效；sanity check 通过 |

每周末跑 chaos QA round 验证无回归。
