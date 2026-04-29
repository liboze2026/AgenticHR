# Spec 0429-D — 岗位 × 候选人 人工决策闸门

> 状态: design  
> 日期: 2026-04-29

## 背景

岗位编辑页 "匹配候选人" Tab 列出硬筛通过候选人 (学历 + 院校等级 + 四项齐全), 当前仅展示, 无人工决策。约面试页候选人下拉直接拉硬筛通过名单 → 任何硬筛通过的人都可被约面, 缺人工闸门。

五维能力筛选 Tab 已有 `matching_results.job_action` (passed/rejected) 但只本地排序, 未与约面试联动, 且必须先跑 LLM 打分才存在。

## 目标

1. HR 在硬筛通过页面 (匹配候选人 Tab) 直接对每候选人按"本岗位通过 / 淘汰 / 清除"操作。
2. 决策 candidate × job 维度独立 (同一候选人对岗位 A 通过、岗位 B 淘汰互不影响)。
3. 约面试候选人下拉 **死卡**: 只列 `action='passed'` 候选人。
4. 不依赖 LLM 五维打分。
5. 五维 Tab 与匹配 Tab 共享同一份决策状态。

## 非目标

- 不引入工作流 (审批链 / 多角色)。
- 不改简历库 (`Resume.status`) 全局状态。
- 不动 `matching_results.job_action` 字段 (保留只读, 未来清理另开 spec)。

## 数据模型

新表 `job_candidate_decision`:

| 列 | 类型 | 约束 |
|---|---|---|
| id | INTEGER | PK autoincr |
| user_id | INTEGER | NOT NULL, FK users(id), index |
| job_id | INTEGER | NOT NULL, FK jobs(id), index |
| candidate_id | INTEGER | NOT NULL, FK intake_candidates(id) ON DELETE CASCADE, index |
| action | VARCHAR(20) | NOT NULL, CHECK in ('passed','rejected') |
| decided_at | DATETIME | NOT NULL, default now |
| updated_at | DATETIME | NOT NULL, default now, on update now |

UNIQUE `(job_id, candidate_id)` — 同一 candidate 对一个 job 只有一行。清除 = 物理删行。

为什么 candidate_id 而非 resume_id:
- 匹配 Tab 数据源 `list_matched_for_job` 返 IntakeCandidate, 前端拿到 `row.id` = candidate.id。
- candidate 是采集源头, resume 是 promote 后产物 (1:1 但晚生成)。决策跟 candidate 走更直观, 不依赖 promote 状态。
- 五维 Tab 的 `matching_result.resume_id` 反查 `IntakeCandidate.promoted_resume_id` 即可换回 candidate_id (已有索引)。

## API

### PATCH /api/jobs/{job_id}/candidates/{candidate_id}/decision

Body:
```json
{"action": "passed"}    // 或 "rejected" / null (清除)
```

Response 200:
```json
{"job_id": 1, "candidate_id": 7, "action": "passed", "decided_at": "..."}
```

错误:
- 404 job 不存在 / 不属当前 user
- 404 candidate 不存在 / 不属当前 user
- 400 action 非法

### GET /api/matching/passed-resumes/{job_id}?action=passed

新增 query 参数 `action`:
- 缺省: 当前行为 (硬筛通过全部, 加 `job_action` 字段)
- `action=passed`: 仅返 `job_action='passed'`
- `action=rejected`: 仅返 `job_action='rejected'`
- `action=undecided`: 仅返无决策行

返回项新增字段:
```json
{"id": 7, "name": "...", ..., "job_action": "passed" | "rejected" | null}
```

### 兼容性

- 旧 `PATCH /api/matching/results/{result_id}/action` 保留, 但内部改写: 同时写 decision 表 (按 result.resume_id → candidate_id 反查), 保证旧前端调用无破坏。matching_results.job_action 字段同步写一份冗余兼容。

## 前端

### Jobs.vue 匹配候选人 Tab

加列 "本岗位决策" (width 180):
```
[通过] [淘汰] [清除]    或    ✓ 已通过 [改]    或    ✗ 已淘汰 [改]
```

排序: `action='passed'` → null → `action='rejected'`, 同组按 created_at 降序。

每行调用 `PATCH /api/jobs/{job_id}/candidates/{id}/decision`, 成功后本地更新 `row.job_action` 重排。

淘汰前弹确认框 (现有 `setJobAction` 已有, 复用)。

### Interviews.vue

`listPassedForJob(jobId)` → `listPassedForJob(jobId, {action: 'passed'})`。

候选人下拉 0 通过提示文案改:
> 该岗位暂无人工标记"通过"的候选人, 请到岗位 → 匹配候选人 Tab 标记。

### Jobs.vue 五维 Tab

`setJobAction(item, action)` 从 `matchingApi.setAction(matching_result.id)` 改为 `decisionApi.set(job_id, candidate_id, action)`。
- `candidate_id` 从 `item` 反查: 后端 list_results 响应已含 `resume_id`, 前端用 `resumeId → candidateId` map (新加端点 `/api/matching/results-with-candidate-id`, 或 list_results 响应直接加 `candidate_id` 字段)。

简化: list_results 响应加 `candidate_id` 字段 (db join), 前端无须额外端点。

## 迁移

`0024_job_candidate_decision.py`:
1. 建表
2. 回填: 遍历 matching_results 中 `job_action IS NOT NULL` 行, 反查 `intake_candidates.promoted_resume_id = matching_results.resume_id` 拿 candidate_id, 写 decision 表。冲突 (UNIQUE 已存在) skip。
3. 回滚: drop table (回填数据丢失可接受, 因 matching_results.job_action 字段未删, 五维 Tab 本地排序仍可工作)。

级联清理: `delete cascade` 走 `intake_candidates.id`。job 删除时, decision 表 `WHERE job_id` 显式删 (沿用现有 cascade.py 模式)。

## Edge cases

| 场景 | 行为 |
|---|---|
| 候选人未 promote 但被标 passed → 后续 promote → 约面试 | decision 跟 candidate 走, promote 后 candidate_id 不变, passed 状态保持 → Interviews 下拉返 promoted resume → 正常 |
| 候选人被标 passed 后 IntakeCandidate 状态变 abandoned/timed_out | `_complete_query` 已过滤 abandoned, 不再出现在 list_matched_for_job → 自动从下拉消失 |
| 岗位 school_tier_min 调严, 候选人原 passed 但现在不达标 | `list_matched_for_job` 硬筛过滤掉 → decision 行残留无害 (UI 看不到), 下次再放宽门槛会复活原状态 |
| 同 candidate 不同 job 决策 | UNIQUE(job_id, candidate_id), 互不冲突 |

## 测试矩阵

- 单测 `tests/modules/matching/test_decision_service.py`
  - set passed/rejected/null 幂等
  - 跨 user 隔离 (user 2 设 job 1 candidate 5, user 1 读不到)
  - 同 (job, candidate) UNIQUE 升级而非新增行
- 集成测 `tests/integration/test_decision_router.py`
  - PATCH 端点 200/404/400
  - GET passed-resumes ?action 过滤
  - 旧 PATCH /api/matching/results/{id}/action 兼容写入新表
- E2E: 跑全套 pytest, frontend `npm run build`

## 风险

- 回填脚本对生产 matching_results 的数据敏感: 只读 (SELECT) + 幂等 INSERT OR IGNORE, 不破坏原数据。
- 旧前端缓存命中老 `listPassedForJob` 不带 action 参数: 后端默认行为不变, 旧 UI 仍能工作 (只是没人工闸门效果, 与改造前一致)。
