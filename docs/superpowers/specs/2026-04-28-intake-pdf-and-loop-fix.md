# 2026-04-28 设计文档：intake PDF 路径污染 + 反复发问循环修复

## 0. 背景

会话中暴露两个生产 bug：

1. **陆昊男 PDF 404**：简历库点"查看 PDF"返回 404。DB 查证 `resumes.id=35.pdf_path='简历.pdf'`（裸文件名），磁盘无此文件
2. **黄文慧反复发问**：候选人已在聊天里完整回答硬槽问题，系统每隔几小时仍重新发问

## 1. 根因

### Bug A — PDF 路径污染

**链路**：扩展 PDF 检测函数 (`edge_extension/content.js:1303`) 在卡片标题文字（`"简历.pdf"`）作为兜底 url 返回；当真实下载 `downloadPdf()` 失败时（网络抖动 / iframe 超时 / BOSS 反爬），调用方走 fallback：

```js
pdf_url: realPdfPath || (pdf.present ? pdf.url : null)
```

伪 url `"简历.pdf"` 进 `/collect-chat`。后端 `app/modules/im_intake/router.py:351-356` 不校验直接写：

```python
slots["pdf"].value = body.pdf_url
c.pdf_path = body.pdf_url
```

`promote_to_resume` 把 `candidate.pdf_path` 原样复制到 `Resume.pdf_path`。后续 `/api/resumes/{id}/pdf` 端点 `Path("简历.pdf").resolve()` → `D:\0jingtong\AgenticHR\简历.pdf` → 文件不存在 → 404。

### Bug B — 反复发问循环

`app/modules/im_intake/decision.py:48-64` `decide_next_action`：

```python
hard_unfilled = [k for k in HARD_SLOT_KEYS
                 if k in by and not by[k].value and by[k].ask_count < hard_max]
pending = [k for k in hard_unfilled if _cooled(k)]
if pending:
    return NextAction(type="send_hard", ...)
```

**只看 `slot.value` 是否为空**，不看候选人是否已经在聊天里回答。当 SlotFiller 抽不到（早期 regex bug、LLM 返回空、语义不清）：
- slot.value 仍 NULL
- `intake_status` 不到终态
- `ask_count < 3` + 6h 冷却过 → 重新进入 send_hard

候选人陷入"她说过 → 系统不知道 → 再问 → 她又答 → 系统又抽不到 → 再问"死循环。

## 2. 修复设计

### Bug A 三层修复

#### A1 — 扩展层：堵源头

文件：`edge_extension/content.js:1303-1318`

去掉 title fallback，让 `intake_checkPdfReceived` 只返回 `present` 标志，不带可能误用的 url：

```js
async function intake_checkPdfReceived(bossId) {
  const cards = document.querySelectorAll(".message-card-wrap.boss-green");
  for (let i = cards.length - 1; i >= 0; i--) {
    const title = (cards[i].querySelector(".message-card-top-title")?.textContent || "").trim();
    if (/您是否同意|拒绝发送|拒绝同意/.test(title)) continue;
    const btns = cards[i].querySelectorAll(".card-btn:not(.disabled)");
    for (const btn of btns) {
      const t = (btn.textContent || "").trim();
      if (/预览|查看|下载/.test(t)) {
        return { present: true };  // 不返 url
      }
    }
  }
  return { present: false };
}
```

调用点改：

```js
pdf_url: realPdfPath  // null 时让后端走 request_pdf 重新索取
```

#### A2 — 后端层：防御性校验

文件：`app/modules/im_intake/router.py:320-360`

```python
def _is_valid_pdf_url(url: str) -> bool:
    if not url:
        return False
    if url.startswith(("http://", "https://")):
        return True
    try:
        p = Path(url).resolve()
        storage_root = Path(settings.resume_storage_path).resolve()
        return str(p).startswith(str(storage_root)) and p.exists()
    except (OSError, ValueError):
        return False

# collect_chat 内
if body.pdf_present and body.pdf_url:
    if _is_valid_pdf_url(body.pdf_url) and not c.pdf_path:
        slots = svc.ensure_slot_rows(c.id)
        slots["pdf"].value = body.pdf_url
        slots["pdf"].source = "plugin_detected"
        slots["pdf"].answered_at = datetime.now(timezone.utc)
        c.pdf_path = body.pdf_url
        db.commit()
        _audit_safe("f4_pdf_received", "pdf_uploaded", c.id, ...)
    elif not _is_valid_pdf_url(body.pdf_url):
        _audit_safe("f4_pdf_invalid_path", "rejected", c.id,
                    {"received": body.pdf_url}, reviewer_id=user_id)
```

#### A3 — 清理脚本

新建 `scripts/cleanup_invalid_pdf_paths.py`：

```python
"""扫所有 IntakeCandidate + Resume，pdf_path 既非有效本地路径也非 http URL → 置空。
   关联 IntakeCandidate.pdf 槽位 value 清空、ask_count 重置；intake_status=complete 的拉回 collecting，
   让 Step2 自动重新索取。"""
```

输出报告：影响行数、回退候选人数、置空 resume 数。**默认 dry-run**，加 `--apply` 才落库。

### Bug B 防循环修复

#### B1 — analyze_chat 抽完检查

文件：`app/modules/im_intake/service.py:94-200` `analyze_chat`

现有逻辑（line 117-138）抽完一次。增加：

```python
# SlotFiller 跑完后重查 slot
slots_after = self.db.query(IntakeSlot).filter_by(candidate_id=candidate.id).all()
slots_by = {s.slot_key: s for s in slots_after}
still_unfilled = [k for k in HARD_SLOT_KEYS
                  if k in slots_by and not slots_by[k].value]

# 防循环：候选人有多条回复 + 已问过至少一次 + 抽完仍空
# → 多半是语义不清或 LLM 抽取盲区，再问也白搭，转人工
candidate_msg_count = sum(
    1 for m in merged_messages
    if m.get("sender_id") == candidate.boss_id
)
already_asked_some = any(
    slots_by[k].ask_count > 0 for k in HARD_SLOT_KEYS if k in slots_by
)
if (still_unfilled and candidate_msg_count >= 2 and already_asked_some):
    candidate.intake_status = "pending_human"
    candidate.intake_completed_at = datetime.now(timezone.utc)
    self.db.commit()
    _audit_safe("f4_extract_failed_pending_human", "auto_pending", candidate.id,
                {"unfilled": still_unfilled,
                 "candidate_msg_count": candidate_msg_count},
                reviewer_id=self.user_id or None)
    return NextAction(type="mark_pending_human")
```

**阈值**：`candidate_msg_count >= 2` + `already_asked_some=True`。
- 候选人没回过：保持 send_hard
- 候选人回 1 条：保持 send_hard（可能新回复）
- 候选人回 ≥2 条 + 之前问过 + 还抽不到：转人工

#### B2 — autoscan_rank 降权

文件：`app/modules/im_intake/router.py:547-577`

加优先级排序键：`chat_snapshot 非空 + 所有 hard slot 空` → 末位。

```python
from sqlalchemy import literal, select

# 候选人 has_unfilled_after_chat 标志：聊过但还有 slot 空
unfilled_count_subq = (
    select(func.count(IntakeSlot.slot_key))
    .where(IntakeSlot.candidate_id == IntakeCandidate.id)
    .where(IntakeSlot.slot_key.in_(list(HARD_SLOT_KEYS)))
    .where(IntakeSlot.value == "")
    .correlate(IntakeCandidate)
    .scalar_subquery()
)
has_chat = case((IntakeCandidate.chat_snapshot.is_(None), 0), else_=1)

rows = (
    db.query(IntakeCandidate)
    .filter(IntakeCandidate.user_id == user_id)
    .filter(IntakeCandidate.intake_status.in_(["collecting", "awaiting_reply"]))
    .order_by(
        # 第一档：collecting 优先
        case((IntakeCandidate.intake_status == "collecting", 0), else_=1),
        # 第二档：聊过且仍有空槽 → 降到末位（很可能是抽取漏）
        case((and_(has_chat == 1, unfilled_count_subq > 0), 1), else_=0),
        IntakeCandidate.updated_at.asc(),
    )
    .limit(limit)
    .all()
)
```

#### B3 — 黄文慧数据修复

DB 查 `name LIKE '%黄文慧%'` 的 candidate，跑 `/reextract` 或脚本补 slot；若 SlotFiller 仍抽不到，转 `pending_human`。

## 3. 测试策略

### 单元测试

| 编号 | 文件 | 用例 |
|---|---|---|
| T-A2-1 | `tests/modules/im_intake/test_collect_chat_pdf_validation.py` | 合法绝对路径写入 pdf_path |
| T-A2-2 | 同上 | 合法 http URL 写入 pdf_path |
| T-A2-3 | 同上 | 裸文件名"简历.pdf" 拒绝 + audit + pdf_path 仍 NULL |
| T-A2-4 | 同上 | 路径越界（不在 storage_root 下）拒绝 |
| T-A2-5 | 同上 | 文件不存在的本地路径拒绝 |
| T-A3-1 | `tests/scripts/test_cleanup_invalid_pdf_paths.py` | dry-run 输出报告不改库 |
| T-A3-2 | 同上 | --apply 修复无效行 + 候选人状态回退 |
| T-B1-1 | `tests/modules/im_intake/test_analyze_chat_pending_human.py` | 候选人 0 回复 → send_hard（不变） |
| T-B1-2 | 同上 | 候选人 1 回复 + 已问过 + 抽不到 → send_hard（不变） |
| T-B1-3 | 同上 | 候选人 2 回复 + 已问过 + 抽不到 → mark_pending_human |
| T-B1-4 | 同上 | 候选人 2 回复 + 已问过 + SlotFiller 抽到了 → 不进 pending_human |
| T-B2-1 | `tests/modules/im_intake/test_autoscan_rank_priority.py` | chat_snapshot 非空 + slot 空 → 排到末位 |
| T-B2-2 | 同上 | chat_snapshot 空 → 正常优先级 |

### 全量测试

- 后端：`pytest tests/modules/im_intake tests/modules/resume tests/scripts -v`
- 前端：`pnpm test && pnpm typecheck`

### E2E 浏览器验证

1. 起 backend + frontend
2. 登录管理界面
3. 简历库找陆昊男
   - **修复前**：点查看 PDF → `404 PDF 文件不存在` 弹窗
   - **修复后**（跑过清理脚本）：陆昊男状态回 `collecting`，从简历库消失（因 pdf 槽空）
4. 候选人列表（intake）
   - 找黄文慧 → 点重抽 → 验证 toast
   - 验证状态推进
5. 截图对比

## 4. 数据迁移

清理脚本 `scripts/cleanup_invalid_pdf_paths.py` 处理三个层级：

1. `intake_candidates`：`pdf_path` 无效 → 置 NULL；`intake_status='complete'` 的拉回 `collecting`，清 `intake_completed_at`、`promoted_resume_id` 解除关联
2. `intake_slots(slot_key='pdf')`：value 无效 → 清 value、source=NULL、answered_at=NULL、ask_count=0
3. `resumes`：`pdf_path` 无效 → 置空字符串（model 默认值 `""`）

**安全措施**：
- 操作前自动备份 `data/recruitment.db` → `data/recruitment.db.bak.YYYYMMDD_HHMMSS`
- 默认 dry-run，输出影响行数
- `--apply` 才真正改库

## 5. 回滚

| 范围 | 回滚动作 |
|---|---|
| 代码 | `git revert <commit>` |
| DB | 还原 `data/recruitment.db.bak.*` 备份 |
| 扩展 | 重新打包旧版 `edge_extension/` 装回 |

## 6. 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| Bug B 阈值 | candidate_msg≥2 + already_asked_some | ≥2 表明配合且已尝试沟通；single 回复可能是新回复，给系统再问的机会 |
| pending_human 入口 | analyze_chat 内联 | 已经在跑 SlotFiller，inline 决策最简单；避免新 action type 改动接口 |
| 降权策略 | autoscan_rank 排序 + B1 inline 双保险 | rank 降权减少被 pick 频率；B1 防真被 pick 后死循环 |
| 清理脚本默认行为 | dry-run | 用户可见影响范围再决定，避免误操作 |
| 陆昊男止血 | 跑清理脚本 | 自动化方案；候选人下次互动会被系统自动重新索要简历 |

## 7. 不在本次范围

- 不重构 SlotFiller 抽取逻辑
- 不改 outbox 调度
- 不动 intake_status 状态机（仅用现有 pending_human 转移）
- 不改前端"重抽"按钮逻辑
