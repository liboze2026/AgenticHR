# F4 Backend Scheduler + Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 F4 Intake 加后端常驻定时调度器 + 消息发件箱（outbox），让"定期扫候选人→给缺信息的人生成待发问题→扩展拉队列实发"这条链路独立于浏览器扩展的 `chrome.alarms`，实现真正的"关闭系统后重启自动续跑"。

**Architecture:**
- 后端 FastAPI `lifespan` 启动一个**后台线程**（daemon），每 5 分钟扫一次 `intake_candidates` 里 status ∈ {collecting, awaiting_reply} 的人，对每人跑现有 `decide_next_action`；若决策是 `send_hard / request_pdf / send_soft`，写一条记录到新的 `intake_outbox` 表（有 pending/claimed/sent 状态）。
- 扩展 `background.js` 用 `chrome.alarms`（period=0.5min，MV3 支持）每 30s 调后端 `POST /api/intake/outbox/claim`，拉到任务后转交 `content.js` 走现有 Boss 发送流程，发完回调 `POST /api/intake/outbox/{id}/ack`，后端再调现有 `IntakeService.record_asked` 更新 slot 计数和状态。
- 调度器同时跑过期清理：`intake_candidates.updated_at < now - 14d AND status IN (collecting, awaiting_reply)` → 标为 `abandoned`。
- 复用 `decide_next_action`（[decision.py:24](app/modules/im_intake/decision.py)）、`record_asked`（[service.py:164](app/modules/im_intake/service.py)）、`apply_terminal`（[service.py:199](app/modules/im_intake/service.py)）；不重造状态机。

**Tech Stack:** FastAPI / SQLAlchemy / Alembic / SQLite / pytest / chrome MV3 extension (Service Worker + chrome.alarms)

**User-confirmed parameters:**
- `hard_max=3`（不改）
- `ask_cooldown_h=6`（不改）
- scheduler scan interval：**5 分钟**
- extension poll interval：**30 秒**（`chrome.alarms` `periodInMinutes=0.5`，MV3 Chrome ≥120 支持）
- `expires_days=14`
- 幂等：一个候选人同时最多一条 `pending` 或 `claimed` outbox
- 不加 priority 字段

---

## File Structure

**Create:**
- `migrations/versions/0017_f4_outbox_and_expiry.py` — Alembic migration: `intake_outbox` 表 + `intake_candidates.expires_at` 列
- `app/modules/im_intake/outbox_model.py` — `IntakeOutbox` SQLAlchemy 模型
- `app/modules/im_intake/outbox_service.py` — 生成/认领/ack/清理过期 四个函数
- `app/modules/im_intake/scheduler.py` — daemon 线程主循环
- `tests/modules/im_intake/test_migration_0017.py`
- `tests/modules/im_intake/test_outbox_model.py`
- `tests/modules/im_intake/test_outbox_service.py`
- `tests/modules/im_intake/test_scheduler.py`
- `tests/modules/im_intake/test_router_outbox.py`

**Modify:**
- `app/config.py` — 新增 `f4_scheduler_interval_sec`、`f4_expires_days`、`f4_scheduler_enabled`
- `app/modules/im_intake/candidate_model.py` — 加 `expires_at` 列（SQLAlchemy 层）
- `app/modules/im_intake/schemas.py` — 加 `OutboxClaimItem`、`OutboxAckIn`
- `app/modules/im_intake/router.py` — 加 `POST /api/intake/outbox/claim`、`POST /api/intake/outbox/{id}/ack`
- `app/main.py` — `lifespan` 里启动 scheduler 线程
- `edge_extension/background.js` — 加 `outbox_poll` alarm + fetch 任务 + 转发
- `edge_extension/content.js` — 新增消息处理：`intake_outbox_dispatch` → 走现有发送 → 回 ack

---

## Task 1: Migration 0017 — `intake_outbox` + `expires_at`

**Files:**
- Create: `migrations/versions/0017_f4_outbox_and_expiry.py`
- Test: `tests/modules/im_intake/test_migration_0017.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/im_intake/test_migration_0017.py
import sqlite3
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _seed_base(db: str):
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50), password_hash VARCHAR(200),
            display_name VARCHAR(100) DEFAULT '', is_active BOOLEAN DEFAULT 1,
            created_at DATETIME);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0, title VARCHAR(200), department VARCHAR(100) DEFAULT '',
            education_min VARCHAR(50) DEFAULT '', work_years_min INTEGER DEFAULT 0,
            work_years_max INTEGER DEFAULT 99, salary_min REAL DEFAULT 0, salary_max REAL DEFAULT 0,
            required_skills TEXT DEFAULT '', soft_requirements TEXT DEFAULT '',
            greeting_templates TEXT DEFAULT '', is_active BOOLEAN DEFAULT 1,
            created_at DATETIME, updated_at DATETIME);
        CREATE TABLE resumes (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER DEFAULT 0, name VARCHAR(100), phone VARCHAR(20) DEFAULT '',
            email VARCHAR(200) DEFAULT '', education VARCHAR(50) DEFAULT '',
            created_at DATETIME, updated_at DATETIME);
    """)
    conn.commit()
    conn.close()


def _cfg(db: str) -> Config:
    cfg = Config("migrations/alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    return cfg


def test_0017_creates_outbox_and_adds_expires_at(tmp_path):
    db = tmp_path / "t.db"
    _seed_base(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0017")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)

    # intake_outbox table exists with expected columns
    assert "intake_outbox" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("intake_outbox")}
    for needed in ("id", "candidate_id", "user_id", "action_type", "text", "slot_keys",
                   "status", "scheduled_for", "claimed_at", "sent_at", "attempts",
                   "last_error", "created_at"):
        assert needed in cols, needed

    # intake_candidates.expires_at exists
    cand_cols = {c["name"] for c in insp.get_columns("intake_candidates")}
    assert "expires_at" in cand_cols

    # Index for efficient polling
    idx = {ix["name"] for ix in insp.get_indexes("intake_outbox")}
    assert "ix_intake_outbox_status_scheduled" in idx


def test_0017_reversible(tmp_path):
    db = tmp_path / "t.db"
    _seed_base(str(db))
    cfg = _cfg(str(db))
    command.stamp(cfg, "0009")
    command.upgrade(cfg, "0017")
    command.downgrade(cfg, "0016")

    eng = sa.create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    insp = sa.inspect(eng)
    assert "intake_outbox" not in insp.get_table_names()
    cand_cols = {c["name"] for c in insp.get_columns("intake_candidates")}
    assert "expires_at" not in cand_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_migration_0017.py -v`
Expected: FAIL — revision `0017` not found.

- [ ] **Step 3: Write migration**

```python
# migrations/versions/0017_f4_outbox_and_expiry.py
"""F4 outbox + intake_candidates.expires_at

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intake_outbox',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('candidate_id', sa.Integer, nullable=False),
        sa.Column('user_id', sa.Integer, nullable=False, server_default='0'),
        sa.Column('action_type', sa.String(32), nullable=False),
        sa.Column('text', sa.Text, nullable=False, server_default=''),
        sa.Column('slot_keys', sa.JSON, nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('scheduled_for', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column('claimed_at', sa.DateTime, nullable=True),
        sa.Column('sent_at', sa.DateTime, nullable=True),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['candidate_id'], ['intake_candidates.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_intake_outbox_status_scheduled', 'intake_outbox', ['status', 'scheduled_for'])
    op.create_index('ix_intake_outbox_user_status', 'intake_outbox', ['user_id', 'status'])
    op.create_index('ix_intake_outbox_candidate_status', 'intake_outbox', ['candidate_id', 'status'])

    with op.batch_alter_table('intake_candidates') as batch_op:
        batch_op.add_column(sa.Column('expires_at', sa.DateTime, nullable=True))
        batch_op.create_index('ix_intake_candidates_expires_at', ['expires_at'])


def downgrade() -> None:
    with op.batch_alter_table('intake_candidates') as batch_op:
        batch_op.drop_index('ix_intake_candidates_expires_at')
        batch_op.drop_column('expires_at')
    op.drop_index('ix_intake_outbox_candidate_status', table_name='intake_outbox')
    op.drop_index('ix_intake_outbox_user_status', table_name='intake_outbox')
    op.drop_index('ix_intake_outbox_status_scheduled', table_name='intake_outbox')
    op.drop_table('intake_outbox')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_migration_0017.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/0017_f4_outbox_and_expiry.py tests/modules/im_intake/test_migration_0017.py
git commit -m "feat(f4): migration 0017 — intake_outbox table + intake_candidates.expires_at"
```

---

## Task 2: `IntakeOutbox` SQLAlchemy model + `expires_at` on `IntakeCandidate`

**Files:**
- Create: `app/modules/im_intake/outbox_model.py`
- Modify: `app/modules/im_intake/candidate_model.py`
- Test: `tests/modules/im_intake/test_outbox_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/im_intake/test_outbox_model.py
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox


def _make_session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_outbox_model_roundtrip_and_defaults():
    db = _make_session()
    c = IntakeCandidate(user_id=1, boss_id="bx1", name="张三", intake_status="collecting",
                        source="plugin",
                        intake_started_at=datetime.now(timezone.utc))
    db.add(c); db.commit()
    ob = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                      text="请问您的薪资期望？", slot_keys=["salary_expectation"])
    db.add(ob); db.commit()
    db.refresh(ob)
    assert ob.id > 0
    assert ob.status == "pending"
    assert ob.attempts == 0
    assert ob.slot_keys == ["salary_expectation"]


def test_intake_candidate_has_expires_at():
    db = _make_session()
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=1, boss_id="bx2", name="李四", intake_status="collecting",
                        source="plugin", intake_started_at=now, expires_at=now)
    db.add(c); db.commit(); db.refresh(c)
    assert c.expires_at == now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_outbox_model.py -v`
Expected: FAIL — `ModuleNotFoundError: outbox_model` or `expires_at` attr missing.

- [ ] **Step 3: Create model + add column**

```python
# app/modules/im_intake/outbox_model.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Index
from app.database import Base


class IntakeOutbox(Base):
    __tablename__ = "intake_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(Integer, ForeignKey("intake_candidates.id", ondelete="CASCADE"),
                          nullable=False)
    user_id = Column(Integer, nullable=False, default=0)
    action_type = Column(String(32), nullable=False)  # send_hard / request_pdf / send_soft
    text = Column(Text, nullable=False, default="")
    slot_keys = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending")  # pending/claimed/sent/failed/expired
    scheduled_for = Column(DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    claimed_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_intake_outbox_status_scheduled", "status", "scheduled_for"),
        Index("ix_intake_outbox_user_status", "user_id", "status"),
        Index("ix_intake_outbox_candidate_status", "candidate_id", "status"),
    )
```

Edit `app/modules/im_intake/candidate_model.py` — add one line after `intake_completed_at`:

```python
# after: intake_completed_at = Column(DateTime, nullable=True)
expires_at = Column(DateTime, nullable=True)
```

And add index to `__table_args__`:

```python
Index("ix_intake_candidates_expires_at", "expires_at"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_outbox_model.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/outbox_model.py app/modules/im_intake/candidate_model.py tests/modules/im_intake/test_outbox_model.py
git commit -m "feat(f4): IntakeOutbox model + IntakeCandidate.expires_at column"
```

---

## Task 3: `outbox_service.generate_for_candidate` — 幂等生成一条待发任务

**Files:**
- Create: `app/modules/im_intake/outbox_service.py`
- Test: `tests/modules/im_intake/test_outbox_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/im_intake/test_outbox_service.py
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.outbox_service import generate_for_candidate


def _make_session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _mk_candidate(db, boss_id="bxA"):
    c = IntakeCandidate(user_id=1, boss_id=boss_id, name="A", intake_status="collecting",
                        source="plugin", intake_started_at=datetime.now(timezone.utc))
    db.add(c); db.commit()
    return c


def test_generate_inserts_pending_row_for_send_hard():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="问薪资？", meta={"slot_keys": ["salary_expectation"]})
    row = generate_for_candidate(db, c, act)
    assert row is not None
    assert row.status == "pending"
    assert row.action_type == "send_hard"
    assert row.slot_keys == ["salary_expectation"]


def test_generate_is_idempotent_when_pending_exists():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="问薪资？", meta={"slot_keys": ["salary_expectation"]})
    first = generate_for_candidate(db, c, act)
    second = generate_for_candidate(db, c, act)
    assert second is None
    assert db.query(IntakeOutbox).filter_by(candidate_id=c.id).count() == 1
    assert first.status == "pending"


def test_generate_is_idempotent_when_claimed_exists():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="问薪资？", meta={"slot_keys": ["salary_expectation"]})
    first = generate_for_candidate(db, c, act)
    first.status = "claimed"; db.commit()
    second = generate_for_candidate(db, c, act)
    assert second is None


def test_generate_skips_non_send_actions():
    db = _make_session()
    c = _mk_candidate(db)
    for typ in ("wait_reply", "wait_pdf", "complete", "abandon", "mark_pending_human"):
        assert generate_for_candidate(db, c, NextAction(type=typ)) is None
    assert db.query(IntakeOutbox).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: FAIL — `ModuleNotFoundError: outbox_service`.

- [ ] **Step 3: Implement**

```python
# app/modules/im_intake/outbox_service.py
"""F4 outbox: 一条发件箱 = 一条待扩展代为发送的 Boss 消息。

单一职责：生成 / 认领 / 回执 / 过期清理。
与现有 decision.py + service.py 解耦——它只接受 NextAction，不决定状态机。
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction

SEND_ACTIONS = {"send_hard", "request_pdf", "send_soft"}


def generate_for_candidate(db: Session, candidate: IntakeCandidate,
                           action: NextAction) -> IntakeOutbox | None:
    """给候选人生成一条待发 outbox；若已有 pending/claimed 则返回 None（幂等）。"""
    if action.type not in SEND_ACTIONS:
        return None
    existing = (db.query(IntakeOutbox)
                .filter_by(candidate_id=candidate.id)
                .filter(IntakeOutbox.status.in_(("pending", "claimed")))
                .first())
    if existing is not None:
        return None
    row = IntakeOutbox(
        candidate_id=candidate.id,
        user_id=candidate.user_id,
        action_type=action.type,
        text=action.text or "",
        slot_keys=action.meta.get("slot_keys") or action.meta.get("questions") or [],
        status="pending",
        scheduled_for=datetime.now(timezone.utc),
    )
    db.add(row); db.commit(); db.refresh(row)
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/outbox_service.py tests/modules/im_intake/test_outbox_service.py
git commit -m "feat(f4): outbox_service.generate_for_candidate (idempotent)"
```

---

## Task 4: `outbox_service.claim_batch` — 扩展批量拉取待发任务

**Files:**
- Modify: `app/modules/im_intake/outbox_service.py`
- Modify: `tests/modules/im_intake/test_outbox_service.py`

- [ ] **Step 1: Append failing test**

Append to `tests/modules/im_intake/test_outbox_service.py`:

```python
from app.modules.im_intake.outbox_service import claim_batch


def test_claim_batch_transitions_pending_to_claimed():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    generate_for_candidate(db, c, act)

    items = claim_batch(db, user_id=1, limit=5)
    assert len(items) == 1
    assert items[0].status == "claimed"
    assert items[0].claimed_at is not None


def test_claim_batch_is_user_scoped():
    db = _make_session()
    c1 = _mk_candidate(db, boss_id="bxU1")
    c2 = _mk_candidate(db, boss_id="bxU2"); c2.user_id = 2; db.commit()
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    generate_for_candidate(db, c1, act)
    generate_for_candidate(db, c2, act)

    u1_items = claim_batch(db, user_id=1, limit=10)
    assert len(u1_items) == 1
    assert u1_items[0].candidate_id == c1.id


def test_claim_batch_respects_limit_and_fifo():
    db = _make_session()
    for i in range(5):
        c = _mk_candidate(db, boss_id=f"bx{i}")
        act = NextAction(type="send_hard", text=f"Q{i}", meta={"slot_keys": ["phone"]})
        generate_for_candidate(db, c, act)
    items = claim_batch(db, user_id=1, limit=3)
    assert len(items) == 3
    # FIFO by scheduled_for — earliest three
    texts = [x.text for x in items]
    assert texts == ["Q0", "Q1", "Q2"]


def test_claim_batch_skips_already_claimed():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    row = generate_for_candidate(db, c, act)
    row.status = "claimed"; db.commit()
    assert claim_batch(db, user_id=1, limit=10) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'claim_batch'`.

- [ ] **Step 3: Implement**

Append to `app/modules/im_intake/outbox_service.py`:

```python
def claim_batch(db: Session, user_id: int, limit: int = 5) -> list[IntakeOutbox]:
    """原子认领一批 pending outbox（→ claimed），返回给扩展去发送。"""
    now = datetime.now(timezone.utc)
    rows = (db.query(IntakeOutbox)
            .filter_by(user_id=user_id, status="pending")
            .filter(IntakeOutbox.scheduled_for <= now)
            .order_by(IntakeOutbox.scheduled_for.asc(), IntakeOutbox.id.asc())
            .limit(limit)
            .all())
    for r in rows:
        r.status = "claimed"
        r.claimed_at = now
        r.attempts += 1
    db.commit()
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/outbox_service.py tests/modules/im_intake/test_outbox_service.py
git commit -m "feat(f4): outbox_service.claim_batch — atomic FIFO claim scoped per user"
```

---

## Task 5: `outbox_service.ack` — 扩展回执成功/失败

**Files:**
- Modify: `app/modules/im_intake/outbox_service.py`
- Modify: `tests/modules/im_intake/test_outbox_service.py`

ack 成功时必须调用现有 `IntakeService.record_asked` 推进 slot 状态（ask_count+1、asked_at、candidate.intake_status → awaiting_reply）。DRY。

- [ ] **Step 1: Append failing test**

```python
# append to tests/modules/im_intake/test_outbox_service.py
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_service import ack_sent, ack_failed


def test_ack_sent_marks_row_and_updates_candidate_slots():
    db = _make_session()
    c = _mk_candidate(db)
    # Pre-create slot rows so record_asked can find them
    s = IntakeSlot(candidate_id=c.id, slot_key="phone", slot_category="hard")
    db.add(s); db.commit()
    act = NextAction(type="send_hard", text="问手机号？", meta={"slot_keys": ["phone"]})
    row = generate_for_candidate(db, c, act)
    row.status = "claimed"; db.commit()

    ack_sent(db, row.id)
    db.refresh(row); db.refresh(c); db.refresh(s)
    assert row.status == "sent"
    assert row.sent_at is not None
    assert c.intake_status == "awaiting_reply"
    assert s.ask_count == 1
    assert s.asked_at is not None


def test_ack_failed_keeps_claimed_and_records_error():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    row = generate_for_candidate(db, c, act)
    row.status = "claimed"; db.commit()

    ack_failed(db, row.id, error="tab closed")
    db.refresh(row); db.refresh(c)
    # 失败保留为 pending 以便下次再试（attempts 已在 claim 时+1）
    assert row.status == "pending"
    assert row.last_error == "tab closed"
    assert c.intake_status == "collecting"  # not advanced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'ack_sent'`.

- [ ] **Step 3: Implement**

Append to `app/modules/im_intake/outbox_service.py`:

```python
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.service import IntakeService


def ack_sent(db: Session, outbox_id: int) -> IntakeOutbox | None:
    row = db.query(IntakeOutbox).filter_by(id=outbox_id).first()
    if row is None or row.status != "claimed":
        return row
    candidate = db.query(IntakeCandidate).filter_by(id=row.candidate_id).first()
    if candidate is None:
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc)
        db.commit()
        return row

    # Reuse existing state-machine side-effects.
    svc = IntakeService(db=db, user_id=candidate.user_id)
    action = NextAction(type=row.action_type, text=row.text or "",
                        meta={"slot_keys": row.slot_keys or []})
    # record_asked writes asked_at / ask_count / candidate.intake_status=awaiting_reply
    svc.record_asked(candidate, action)

    row.status = "sent"
    row.sent_at = datetime.now(timezone.utc)
    db.commit()
    return row


def ack_failed(db: Session, outbox_id: int, error: str = "") -> IntakeOutbox | None:
    row = db.query(IntakeOutbox).filter_by(id=outbox_id).first()
    if row is None:
        return None
    row.status = "pending"   # re-queue; attempts already incremented on claim
    row.last_error = error[:2000] if error else None
    row.claimed_at = None
    db.commit()
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/outbox_service.py tests/modules/im_intake/test_outbox_service.py
git commit -m "feat(f4): outbox_service ack_sent/ack_failed — delegate to IntakeService.record_asked"
```

---

## Task 6: `outbox_service.cleanup_expired` — 14 天过期候选人标 abandoned

**Files:**
- Modify: `app/modules/im_intake/outbox_service.py`
- Modify: `tests/modules/im_intake/test_outbox_service.py`

- [ ] **Step 1: Append failing test**

```python
# append to tests/modules/im_intake/test_outbox_service.py
from datetime import timedelta
from app.modules.im_intake.outbox_service import cleanup_expired


def test_cleanup_expired_abandons_old_candidates_and_expires_outbox():
    db = _make_session()
    now = datetime.now(timezone.utc)
    old = IntakeCandidate(user_id=1, boss_id="bxOld", name="O",
                          intake_status="collecting", source="plugin",
                          intake_started_at=now - timedelta(days=20),
                          expires_at=now - timedelta(days=1))
    fresh = IntakeCandidate(user_id=1, boss_id="bxFresh", name="F",
                            intake_status="collecting", source="plugin",
                            intake_started_at=now,
                            expires_at=now + timedelta(days=10))
    db.add_all([old, fresh]); db.commit()
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    row = generate_for_candidate(db, old, act)

    stats = cleanup_expired(db, now=now)
    db.refresh(old); db.refresh(fresh); db.refresh(row)
    assert old.intake_status == "abandoned"
    assert fresh.intake_status == "collecting"
    assert row.status == "expired"
    assert stats["abandoned"] == 1
    assert stats["expired_outbox"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'cleanup_expired'`.

- [ ] **Step 3: Implement**

Append to `app/modules/im_intake/outbox_service.py`:

```python
def cleanup_expired(db: Session, now: datetime | None = None) -> dict:
    """标记 expires_at < now 且仍在进行中的候选人为 abandoned；其 pending/claimed outbox → expired。"""
    now = now or datetime.now(timezone.utc)
    to_abandon = (db.query(IntakeCandidate)
                  .filter(IntakeCandidate.expires_at.isnot(None))
                  .filter(IntakeCandidate.expires_at < now)
                  .filter(IntakeCandidate.intake_status.in_(("collecting", "awaiting_reply")))
                  .all())
    abandoned_ids = [c.id for c in to_abandon]
    for c in to_abandon:
        c.intake_status = "abandoned"
        c.intake_completed_at = now
    expired_cnt = 0
    if abandoned_ids:
        expired_cnt = (db.query(IntakeOutbox)
                       .filter(IntakeOutbox.candidate_id.in_(abandoned_ids))
                       .filter(IntakeOutbox.status.in_(("pending", "claimed")))
                       .update({"status": "expired"}, synchronize_session=False))
    db.commit()
    return {"abandoned": len(abandoned_ids), "expired_outbox": int(expired_cnt)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/outbox_service.py tests/modules/im_intake/test_outbox_service.py
git commit -m "feat(f4): outbox_service.cleanup_expired — abandon past-TTL candidates"
```

---

## Task 7: Scheduler daemon thread — 每 5 分钟扫描全量并生成 outbox

**Files:**
- Create: `app/modules/im_intake/scheduler.py`
- Test: `tests/modules/im_intake/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/im_intake/test_scheduler.py
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.scheduler import scan_once


def _session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _mk_candidate_with_empty_hard_slots(db, user_id=1, boss_id="bx"):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=user_id, boss_id=boss_id, name="A",
                        intake_status="collecting", source="plugin",
                        intake_started_at=now,
                        expires_at=now + timedelta(days=14))
    db.add(c); db.commit()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def test_scan_once_generates_outbox_for_collecting_candidate():
    db = _session()
    c = _mk_candidate_with_empty_hard_slots(db)
    stats = scan_once(db)
    assert stats["generated"] >= 1
    rows = db.query(IntakeOutbox).filter_by(candidate_id=c.id).all()
    assert len(rows) == 1
    assert rows[0].action_type == "send_hard"


def test_scan_once_skips_terminal_candidates():
    db = _session()
    c = _mk_candidate_with_empty_hard_slots(db)
    c.intake_status = "complete"; db.commit()
    stats = scan_once(db)
    assert stats["generated"] == 0
    assert db.query(IntakeOutbox).count() == 0


def test_scan_once_runs_cleanup():
    db = _session()
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=1, boss_id="bxExp", name="X",
                        intake_status="collecting", source="plugin",
                        intake_started_at=now - timedelta(days=20),
                        expires_at=now - timedelta(days=1))
    db.add(c); db.commit()
    stats = scan_once(db)
    db.refresh(c)
    assert c.intake_status == "abandoned"
    assert stats["abandoned"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/modules/im_intake/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: scheduler`.

- [ ] **Step 3: Implement**

```python
# app/modules/im_intake/scheduler.py
"""F4 常驻调度器：每 N 秒扫一次 intake，生成发件箱 + 清理过期。

设计决策：
- 独立 daemon 线程（模式与 app/modules/resume/_ai_parse_worker.py 一致）
- 每轮创建新 Session；失败吞掉日志，不停线程
- scan_once 是纯函数（接收 db），便于单测
"""
import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.decision import decide_next_action
from app.modules.im_intake.outbox_service import generate_for_candidate, cleanup_expired
from app.modules.screening.models import Job
from app.config import settings

logger = logging.getLogger(__name__)

_state = {"running": False, "thread": None}


def scan_once(db: Session) -> dict:
    """扫一次 active intake，生成 outbox；运行一次过期清理。返回统计。"""
    generated = 0
    seen = 0
    hard_max = getattr(settings, "f4_hard_max_asks", 3)
    pdf_to = getattr(settings, "f4_pdf_timeout_hours", 72)
    cooldown = getattr(settings, "f4_ask_cooldown_hours", 6)

    candidates = (db.query(IntakeCandidate)
                  .filter(IntakeCandidate.intake_status.in_(("collecting", "awaiting_reply")))
                  .all())
    for c in candidates:
        seen += 1
        slots = db.query(IntakeSlot).filter_by(candidate_id=c.id).all()
        job = db.query(Job).filter_by(id=c.job_id).first() if c.job_id else None
        action = decide_next_action(c, slots, job,
                                    hard_max=hard_max,
                                    pdf_timeout_h=pdf_to,
                                    ask_cooldown_h=cooldown)
        if generate_for_candidate(db, c, action) is not None:
            generated += 1

    cleanup = cleanup_expired(db)
    return {"seen": seen, "generated": generated, **cleanup}


def _loop(interval_sec: int):
    logger.info("F4 scheduler started, interval=%ss", interval_sec)
    while _state["running"]:
        try:
            db = SessionLocal()
            try:
                stats = scan_once(db)
                logger.info("F4 scan: %s", stats)
            finally:
                db.close()
        except Exception as e:
            logger.exception("F4 scheduler scan failed: %s", e)
        # Sleep in short chunks so stop() reacts promptly.
        for _ in range(interval_sec):
            if not _state["running"]:
                break
            time.sleep(1)
    logger.info("F4 scheduler stopped")


def start(interval_sec: int | None = None) -> None:
    if _state["running"]:
        return
    interval = int(interval_sec if interval_sec is not None
                   else getattr(settings, "f4_scheduler_interval_sec", 300))
    _state["running"] = True
    t = threading.Thread(target=_loop, args=(interval,), daemon=True, name="f4-scheduler")
    _state["thread"] = t
    t.start()


def stop() -> None:
    _state["running"] = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/modules/im_intake/test_scheduler.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/scheduler.py tests/modules/im_intake/test_scheduler.py
git commit -m "feat(f4): scheduler.scan_once + daemon thread (5min default)"
```

---

## Task 8: 配置项 + `app/main.py` lifespan 启动 scheduler

**Files:**
- Modify: `app/config.py`
- Modify: `app/main.py`

- [ ] **Step 1: Add config settings**

Edit `app/config.py` — append inside `Settings` class near other `f4_*` fields:

```python
    # F4 backend scheduler（Task 7）
    f4_scheduler_enabled: bool = True
    f4_scheduler_interval_sec: int = 300
    f4_expires_days: int = 14
```

- [ ] **Step 2: Wire into lifespan**

Edit `app/main.py` — inside `async def lifespan(app)`, after `maybe_start_worker_thread()` block:

```python
    # F4 后端调度器：每 N 秒扫 intake 生成 outbox + 清理过期
    try:
        from app.modules.im_intake import scheduler as _f4_sched
        if settings.f4_scheduler_enabled:
            _f4_sched.start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"F4 scheduler failed to start: {e}")
```

- [ ] **Step 3: Smoke-run the app**

Run: `python -c "from app.main import app; print(app.title)"`
Expected: prints `招聘助手` without exception. Import the module `app.modules.im_intake.scheduler` — no import error.

- [ ] **Step 4: Commit**

```bash
git add app/config.py app/main.py
git commit -m "feat(f4): wire scheduler into FastAPI lifespan + config knobs"
```

---

## Task 9: Router — `POST /api/intake/outbox/claim` + `POST /api/intake/outbox/{id}/ack`

**Files:**
- Modify: `app/modules/im_intake/schemas.py`
- Modify: `app/modules/im_intake/router.py`
- Test: `tests/modules/im_intake/test_router_outbox.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/im_intake/test_router_outbox.py
import os
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.outbox_service import generate_for_candidate


@pytest.fixture(autouse=True)
def _bypass_auth(monkeypatch):
    monkeypatch.setenv("AGENTICHR_TEST_BYPASS_AUTH", "1")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    Base.metadata.create_all(engine)
    yield
    # Clean slate between tests
    with engine.begin() as conn:
        from sqlalchemy import text
        for t in ("intake_outbox", "intake_slots", "intake_candidates"):
            conn.execute(text(f"DELETE FROM {t}"))


def _mk(db, uid=1, boss_id="bxR"):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=uid, boss_id=boss_id, name="R",
                        intake_status="collecting", source="plugin",
                        intake_started_at=now, expires_at=now + timedelta(days=14))
    db.add(c); db.commit()
    db.add(IntakeSlot(candidate_id=c.id, slot_key="phone", slot_category="hard"))
    db.commit()
    return c


def test_outbox_claim_returns_pending_items_and_marks_claimed():
    client = TestClient(app)
    db = SessionLocal()
    try:
        c = _mk(db)
        generate_for_candidate(db, c, NextAction(type="send_hard", text="Q",
                                                 meta={"slot_keys": ["phone"]}))
    finally:
        db.close()

    # NOTE: bypass middleware by setting user_id via header? The current middleware only
    # bypasses when AGENTICHR_TEST_BYPASS_AUTH=1 under pytest. We need to supply user_id.
    # Current deps: get_current_user_id reads request.state.user_id; under bypass, it
    # may return 0. Test should use the user_id that ensure_candidate stored (1).
    # If the dep returns 0 under bypass, we need to align: create candidate with user_id=0.
    # SEE: Task 9 Step 3 — align user_id semantics to match bypass default.

    r = client.post("/api/intake/outbox/claim", json={"limit": 5})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["action_type"] == "send_hard"
    assert items[0]["text"] == "Q"
    assert items[0]["slot_keys"] == ["phone"]

    # second claim returns empty (already claimed)
    r2 = client.post("/api/intake/outbox/claim", json={"limit": 5})
    assert r2.json()["items"] == []


def test_outbox_ack_success_transitions_candidate_and_slot():
    client = TestClient(app)
    db = SessionLocal()
    try:
        c = _mk(db)
        row = generate_for_candidate(db, c, NextAction(type="send_hard", text="Q",
                                                       meta={"slot_keys": ["phone"]}))
        row.status = "claimed"; db.commit()
        row_id = row.id
        cand_id = c.id
    finally:
        db.close()

    r = client.post(f"/api/intake/outbox/{row_id}/ack",
                    json={"success": True})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        row = db.query(IntakeOutbox).filter_by(id=row_id).first()
        c = db.query(IntakeCandidate).filter_by(id=cand_id).first()
        s = db.query(IntakeSlot).filter_by(candidate_id=cand_id, slot_key="phone").first()
        assert row.status == "sent"
        assert c.intake_status == "awaiting_reply"
        assert s.ask_count == 1
    finally:
        db.close()


def test_outbox_ack_failure_requeues():
    client = TestClient(app)
    db = SessionLocal()
    try:
        c = _mk(db)
        row = generate_for_candidate(db, c, NextAction(type="send_hard", text="Q",
                                                       meta={"slot_keys": ["phone"]}))
        row.status = "claimed"; db.commit()
        row_id = row.id
    finally:
        db.close()

    r = client.post(f"/api/intake/outbox/{row_id}/ack",
                    json={"success": False, "error": "tab closed"})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        row = db.query(IntakeOutbox).filter_by(id=row_id).first()
        assert row.status == "pending"
        assert row.last_error == "tab closed"
    finally:
        db.close()
```

Note: the test-bypass returns `user_id` as whatever `get_current_user_id` falls back to. In current router, `Depends(get_current_user_id)` under test-bypass returns what's written in `request.state` — which is nothing. Check behavior of `get_current_user_id` in `app/modules/auth/deps.py` to set test candidate `user_id` correctly — if bypass returns 0, use `uid=0` in `_mk`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/im_intake/test_router_outbox.py -v`
Expected: FAIL — `404 Not Found` (endpoints not yet defined).

- [ ] **Step 3: Add schemas**

Edit `app/modules/im_intake/schemas.py` — append:

```python
class OutboxClaimIn(BaseModel):
    limit: int = Field(5, ge=1, le=50)


class OutboxClaimItem(BaseModel):
    id: int
    candidate_id: int
    action_type: str
    text: str
    slot_keys: list = []
    attempts: int


class OutboxClaimOut(BaseModel):
    items: list[OutboxClaimItem]


class OutboxAckIn(BaseModel):
    success: bool
    error: str = ""
```

(Ensure `BaseModel` and `Field` are already imported at top of file; if not, add them.)

- [ ] **Step 4: Add router endpoints**

Edit `app/modules/im_intake/router.py` — append after `start_conversation`:

```python
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.outbox_service import claim_batch, ack_sent, ack_failed
from app.modules.im_intake.schemas import (
    OutboxAckIn, OutboxClaimIn, OutboxClaimItem, OutboxClaimOut,
)


@router.post("/outbox/claim", response_model=OutboxClaimOut)
def outbox_claim(
    body: OutboxClaimIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    rows = claim_batch(db, user_id=user_id, limit=body.limit)
    return OutboxClaimOut(items=[
        OutboxClaimItem(
            id=r.id, candidate_id=r.candidate_id, action_type=r.action_type,
            text=r.text or "", slot_keys=r.slot_keys or [], attempts=r.attempts,
        ) for r in rows
    ])


@router.post("/outbox/{outbox_id}/ack")
def outbox_ack(
    outbox_id: int,
    body: OutboxAckIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    row = db.query(IntakeOutbox).filter_by(id=outbox_id, user_id=user_id).first()
    if row is None:
        raise HTTPException(404, "outbox not found")
    if body.success:
        ack_sent(db, outbox_id)
    else:
        ack_failed(db, outbox_id, error=body.error)
    return {"ok": True}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/modules/im_intake/test_router_outbox.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/modules/im_intake/router.py app/modules/im_intake/schemas.py tests/modules/im_intake/test_router_outbox.py
git commit -m "feat(f4): HTTP API /api/intake/outbox/claim + /outbox/{id}/ack"
```

---

## Task 10: 扩展 `background.js` — outbox_poll alarm (30s)

**Files:**
- Modify: `edge_extension/background.js`

Chrome MV3: `chrome.alarms` `periodInMinutes` 最小 0.5（30s），Chrome 120+ 支持；之前版本最小 1min。用 `periodInMinutes: 0.5`，并在不支持时回退到 1min（打日志）。

- [ ] **Step 1: Edit `edge_extension/background.js`**

Add constants and helpers near top (after existing `INTAKE_ALARM_*` constants):

```javascript
const OUTBOX_ALARM_NAME = "intake_outbox_poll";
const OUTBOX_ALARM_PERIOD_MIN = 0.5;  // 30s; Chrome 120+ MV3 allows <1min

async function ensureOutboxAlarm() {
  const { intake_autoscan_enabled } = await chrome.storage.local.get(["intake_autoscan_enabled"]);
  if (!intake_autoscan_enabled) {
    await chrome.alarms.clear(OUTBOX_ALARM_NAME);
    return;
  }
  const existing = await chrome.alarms.get(OUTBOX_ALARM_NAME);
  if (!existing) {
    chrome.alarms.create(OUTBOX_ALARM_NAME, { periodInMinutes: OUTBOX_ALARM_PERIOD_MIN });
    console.log("[intake] outbox poll alarm created period=", OUTBOX_ALARM_PERIOD_MIN, "min");
  }
}

async function pollOutboxOnce() {
  const { serverUrl, authToken } = await chrome.storage.local.get(["serverUrl", "authToken"]);
  if (!serverUrl || !authToken) return;
  let resp;
  try {
    resp = await fetch(`${serverUrl}/api/intake/outbox/claim`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 5 }),
    });
  } catch (e) {
    console.warn("[intake] outbox claim fetch failed:", e?.message || e);
    return;
  }
  if (!resp.ok) {
    console.warn("[intake] outbox claim HTTP", resp.status);
    return;
  }
  const data = await resp.json();
  const items = data.items || [];
  if (!items.length) return;

  const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
  if (!tabs.length) {
    // Release items by reporting failure so backend re-queues them.
    for (const it of items) {
      await reportAck(it.id, false, "no Boss tab open");
    }
    return;
  }
  const preferred = tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0];
  for (const it of items) {
    try {
      await chrome.tabs.sendMessage(preferred.id, {
        type: "intake_outbox_dispatch",
        outbox: it,
      });
    } catch (e) {
      await reportAck(it.id, false, `dispatch failed: ${e?.message || e}`);
    }
  }
}

async function reportAck(outboxId, success, error = "") {
  const { serverUrl, authToken } = await chrome.storage.local.get(["serverUrl", "authToken"]);
  if (!serverUrl || !authToken) return;
  try {
    await fetch(`${serverUrl}/api/intake/outbox/${outboxId}/ack`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({ success, error }),
    });
  } catch (e) {
    console.warn("[intake] outbox ack failed:", e?.message || e);
  }
}
```

Extend existing `ensureAlarm`, `onInstalled` install block, `onStartup`, `storage.onChanged` handler to also call `ensureOutboxAlarm`. Final file should call both helpers in each place. Example for `storage.onChanged`:

```javascript
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "intake_autoscan_enabled" in changes) {
    ensureAlarm();
    ensureOutboxAlarm();
  }
});
```

Extend alarm handler:

```javascript
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === INTAKE_ALARM_NAME) {
    // ... existing autoscan tick logic ...
  } else if (alarm.name === OUTBOX_ALARM_NAME) {
    await pollOutboxOnce();
  }
});
```

Add handler for content-script-reported ack results:

```javascript
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "intake_outbox_ack") {
    reportAck(msg.outbox_id, msg.success, msg.error || "").finally(() =>
      sendResponse({ ok: true })
    );
    return true;  // async response
  }
});
```

- [ ] **Step 2: Reload extension, watch console**

1. Chrome → `chrome://extensions` → enable "Developer mode" → Reload 招聘助手.
2. Open the extension's "inspect service worker" console.
3. Toggle `intake_autoscan_enabled` ON via popup.html. Expected console: `[intake] outbox poll alarm created period= 0.5 min`.

- [ ] **Step 3: Commit**

```bash
git add edge_extension/background.js
git commit -m "feat(f4/ext): 30s outbox_poll alarm + fetch+dispatch+ack to backend"
```

---

## Task 11: 扩展 `content.js` — 处理 `intake_outbox_dispatch`

**Files:**
- Modify: `edge_extension/content.js`

复用现有"向 Boss 发消息"流程。新的 dispatch 消息格式：

```js
{ type: "intake_outbox_dispatch", outbox: { id, candidate_id, action_type, text, slot_keys } }
```

处理后通过 `chrome.runtime.sendMessage({ type: "intake_outbox_ack", outbox_id, success, error })` 回 service worker。

- [ ] **Step 1: Locate existing send flow**

Run: `grep -n "sendMessage\|sendChatMessage\|boss_id\|navigate.*chat" edge_extension/content.js | head -40`

Identify the function that already sends a Boss chat message for an autoscan tick (the code added in commit `df0652c feat(extension/f4): chrome.alarms autoscan tick + intake_ rename`).

- [ ] **Step 2: Add the dispatch handler**

Append inside the existing `chrome.runtime.onMessage.addListener(...)` in `content.js`:

```javascript
if (msg?.type === "intake_outbox_dispatch") {
  (async () => {
    const ob = msg.outbox;
    try {
      // Find/open chat for ob.candidate_id via existing open_chat flow, then send ob.text.
      // Reuse the helper already used by intake_autoscan_tick — e.g. `sendIntakeMessage({
      //   candidate_id, text })`. If that helper doesn't exist yet, factor it out of the
      //  autoscan tick handler (Task 11 Step 3 note) and call it here.
      const ok = await sendIntakeMessage({
        candidate_id: ob.candidate_id,
        text: ob.text,
      });
      chrome.runtime.sendMessage({
        type: "intake_outbox_ack",
        outbox_id: ob.id,
        success: !!ok,
        error: ok ? "" : "send returned false",
      });
    } catch (e) {
      chrome.runtime.sendMessage({
        type: "intake_outbox_ack",
        outbox_id: ob.id,
        success: false,
        error: String(e?.message || e).slice(0, 500),
      });
    }
  })();
  return true;
}
```

- [ ] **Step 3: Refactor existing tick handler to share `sendIntakeMessage`**

If the autoscan tick's send code is inline, extract it into `async function sendIntakeMessage({ candidate_id, text }) → boolean` that:
1. Navigates the current chat-list page to the candidate's chat (DOM click, existing selector).
2. Types `text` into `.chat-input` (existing selector).
3. Clicks send (existing selector).
4. Returns `true` if send visibly succeeded, else `false`.

Reference the existing code paths — don't invent selectors. If a single helper already exists, reuse it.

- [ ] **Step 4: Reload extension and smoke-test**

1. Seed one candidate with empty hard slots via backend (use `POST /api/intake/collect-chat` with minimal body, or write a small `scripts/seed_outbox_demo.py`).
2. Wait ≤30s, observe:
   - Service worker console: `[intake] outbox poll ...` and `dispatch` logs.
   - Content script console (on Boss tab): `intake_outbox_dispatch` received, message sent.
   - Backend log: `F4 scan: ...` entries and `outbox/ack success=true`.

- [ ] **Step 5: Commit**

```bash
git add edge_extension/content.js
git commit -m "feat(f4/ext): handle intake_outbox_dispatch + ack back to service worker"
```

---

## Task 12: E2E smoke test checklist

**Files:** (no code)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/modules/im_intake -v`
Expected: all green.

- [ ] **Step 2: Run typecheck (backend has none, verify imports)**

Run: `python -c "import app.main; import app.modules.im_intake.scheduler; import app.modules.im_intake.outbox_service; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Manual restart recovery test**

1. Start backend: `uvicorn app.main:app --reload`.
2. Chrome: load extension, login, toggle autoscan ON.
3. Create a test candidate via the extension (let it scrape one).
4. Verify DB: `sqlite3 data/recruitment.db "SELECT id, boss_id, intake_status, expires_at FROM intake_candidates ORDER BY id DESC LIMIT 5"` — row exists, `intake_status='collecting'`, `expires_at` NOT NULL.
5. **Stop the backend** (Ctrl+C).
6. Wait ~60s.
7. **Restart the backend** (`uvicorn app.main:app`).
8. Within 5 minutes: check backend log for `F4 scan: {'seen': >=1, 'generated': >=1, ...}` and verify `sqlite3 ... "SELECT id, status, text FROM intake_outbox ORDER BY id DESC LIMIT 5"` — at least one `pending` row.
9. Within another 30s: extension claims it; Boss chat window shows the auto-sent message; outbox row flips to `sent`; candidate's `intake_status` → `awaiting_reply`.

- [ ] **Step 4: Manual expiry test**

1. `sqlite3 data/recruitment.db "UPDATE intake_candidates SET expires_at=datetime('now','-1 day') WHERE id=<some collecting id>"`.
2. Wait one scheduler tick (≤5min).
3. Verify: candidate.intake_status='abandoned'; its outbox rows (if any) status='expired'.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-04-24-f4-backend-scheduler.md
git commit -m "docs(f4): implementation plan — backend scheduler + outbox"
```

---

## Notes for the implementer

- **Do NOT touch** `app/core/**` without asking the user (CLAUDE.md rule).
- **Reuse existing** `IntakeService.record_asked`, `decide_next_action`; do not re-implement the state machine in `outbox_service`.
- `chrome.alarms` minimum period is 0.5min on Chrome 120+. On older Chrome, MV3 clamps to 1min silently — functional degradation, not a bug.
- `get_current_user_id` under `AGENTICHR_TEST_BYPASS_AUTH=1` may return 0. Align test fixtures accordingly (use `user_id=0` in seed candidates if `get_current_user_id` falls through). Confirm before writing Task 9 tests.
- The scheduler thread has no explicit stop hook in `lifespan` shutdown. Daemon threads die with the process; for dev reload this is fine. If shutdown cleanup is needed later, call `scheduler.stop()` in a `finally: yield` block.
- Scheduler interval of 300s + extension poll of 30s is sized for a single HR; if N HRs run the same backend, the scan still scales (it's one SELECT with index).
- `intake_autoscan_enabled` storage flag now gates BOTH the existing autoscan alarm AND the new outbox_poll alarm — keep them coupled to avoid a partial-on state confusing HR.
