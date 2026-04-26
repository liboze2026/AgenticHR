# F5 Target-Count + Pause/Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HR 在 `/intake` 输入一个目标候选人数 N，点"开始"后系统自动 loop（收集 + 追问 + 填槽 + 要简历 + 晋级）直到 complete 计数达 N 自停；中途可点"暂停/恢复"控制。

**Architecture:**
- Backend 新增 `intake_user_settings` 表（单表 KV：user_id PK + enabled + target_count），scheduler / autoscan / outbox 三处 API 前置检查。
- 前端 `/intake` 顶部加一张控制卡片（目标输入 + 开始/暂停按钮 + complete/target 进度条 + 状态徽章）。
- Extension 改 chrome.storage 本地 toggle 为"backend settings 为单一真相源，本地 toggle 降级为紧急 kill-switch"（两者都开才跑）。
- 并发硬化：backend claim 硬限 `limit=1`（纵深防御，扩展侧 mutex 已修）。
- 回归：pytest 覆盖并发派发无交错 + 达标自停 + 暂停生效；最后 AI 执行真实 E2E 直到零 bug。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Vue 3 + Element Plus + Chrome MV3 Extension + pytest

**前置状态：** content.js 串行 mutex + schemas.py `wait_reply` literal 已在 worktree 本地修改**未提交**，Task 1 先提交它们。

---

## File Structure

**Backend 新建：**
- `migrations/versions/0018_intake_user_settings.py` — 建表
- `app/modules/im_intake/settings_model.py` — SQLAlchemy `IntakeUserSettings`
- `app/modules/im_intake/settings_service.py` — `get_or_create` / `update_settings` / `is_running` / `complete_count`
- `tests/modules/im_intake/test_migration_0018.py` — 迁移测试
- `tests/modules/im_intake/test_settings_service.py` — 服务单测
- `tests/modules/im_intake/test_outbox_concurrency.py` — 并发派发回归
- `tests/modules/im_intake/test_scheduler_target_pause.py` — scan_once 针对 target/enabled 的行为

**Backend 修改：**
- `app/modules/im_intake/schemas.py` — `wait_reply` literal（已本地改，Task 1 提交）
- `app/modules/im_intake/scheduler.py:scan_once` — group by user_id + 前置 settings 检查
- `app/modules/im_intake/router.py` — 新 `/settings` GET/PUT + `/outbox/claim` `/autoscan/rank` 加前置 gate + claim 硬 `limit=1`
- `app/modules/im_intake/outbox_service.py:claim_batch` — 参数默认改 `limit=1`（纵深）

**Frontend 新建：**
- `frontend/src/api/intakeSettings.js` — `getIntakeSettings` / `updateIntakeSettings`

**Frontend 修改：**
- `frontend/src/views/Intake.vue` — 顶部卡片（输入 + 按钮 + 进度），扩展 `loadSettings` / `saveSettings` 逻辑

**Extension 修改：**
- `edge_extension/background.js` — alarm handler 前置 `fetchSettings`，`enabled=false` 跳过该 tick
- `edge_extension/content.js` — **已本地改串行 dispatch queue**（Task 1 提交）

---

## Task 1: 提交现有并发修复 + schema 修复

**Files:**
- Modify: 已本地编辑的 `app/modules/im_intake/schemas.py` + `edge_extension/content.js`
- Test: `tests/modules/im_intake/test_schemas.py`（如已存在追加；否则新建）

- [ ] **Step 1: 确认本地改动**

Run: `git diff --stat app/modules/im_intake/schemas.py edge_extension/content.js`
Expected: 2 文件变更，`schemas.py` +1/-1，`content.js` +7/-3 附近。

- [ ] **Step 2: 写 schema 单测验 `wait_reply` 可通过**

Write file `tests/modules/im_intake/test_schemas.py`:

```python
from app.modules.im_intake.schemas import NextActionOut


def test_next_action_out_accepts_wait_reply():
    n = NextActionOut(type="wait_reply", text="", slot_keys=[])
    assert n.type == "wait_reply"


def test_next_action_out_accepts_all_decision_types():
    # ActionType literals from decision.py must all be acceptable here.
    for t in ["send_hard", "request_pdf", "wait_pdf", "wait_reply",
              "send_soft", "complete", "mark_pending_human", "abandon"]:
        NextActionOut(type=t, text="", slot_keys=[])
```

- [ ] **Step 3: 运行测试验证通过**

Run: `pytest tests/modules/im_intake/test_schemas.py -v`
Expected: 2 passed

- [ ] **Step 4: 提交**

```bash
git add app/modules/im_intake/schemas.py edge_extension/content.js tests/modules/im_intake/test_schemas.py
git commit -m "fix(f4): serialize outbox dispatch in content.js + schema wait_reply literal

- content.js: add window.__intakeDispatchQueue promise chain so concurrent
  intake_outbox_dispatch messages never interleave chars into the same
  #boss-chat-editor-input (observed 3 outbox rows mashing together in a
  real send on 2026-04-24).
- schemas.py: add 'wait_reply' to NextActionOut.type literal; decide_next_action
  already returns it during hard-slot cooldown but schema rejected it -> 500
  on /collect-chat.
- tests: assert schema accepts all ActionType values from decision.py."
```

---

## Task 2: Outbox claim 硬限 limit=1（纵深防御）

**Files:**
- Modify: `app/modules/im_intake/outbox_service.py` `claim_batch`
- Modify: `app/modules/im_intake/schemas.py` `OutboxClaimIn`
- Test: `tests/modules/im_intake/test_outbox_concurrency.py`（新建）

**Why:** 扩展侧 mutex 是 client-side 保护，backend 兜底：无论 caller 请求 limit 多少，实际只返 1 条，从根上杜绝并发派发。

- [ ] **Step 1: 写失败测试**

Create `tests/modules/im_intake/test_outbox_concurrency.py`:

```python
"""Backend-side concurrency hardening: outbox claim must never return >1.

Client-side (extension content.js) has a mutex after the 2026-04-24 bug where
3 outbox rows mashed together in a single input. Backend is a second line of
defense: even if caller asks for limit=5, we return at most 1.
"""
from datetime import datetime, timezone

import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.outbox_service import claim_batch


@pytest.fixture
def three_pending(db_session):
    db = db_session
    cands = []
    for i in range(3):
        c = IntakeCandidate(user_id=1, boss_id=f"test-{i}", name=f"T{i}",
                            intake_status="collecting", source="plugin")
        db.add(c); db.flush()
        cands.append(c)
    now = datetime.now(timezone.utc)
    for c in cands:
        db.add(IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                            text=f"msg-{c.id}", slot_keys=[], status="pending",
                            scheduled_for=now))
    db.commit()
    return cands


def test_claim_batch_hard_caps_at_one(db_session, three_pending):
    """Even when caller asks limit=5, backend returns at most 1."""
    rows = claim_batch(db_session, user_id=1, limit=5)
    assert len(rows) == 1


def test_claim_batch_default_limit_is_one(db_session, three_pending):
    """Default limit argument is 1 (no caller can accidentally go wider)."""
    rows = claim_batch(db_session, user_id=1)
    assert len(rows) == 1
```

- [ ] **Step 2: 确认测试失败**

Run: `pytest tests/modules/im_intake/test_outbox_concurrency.py -v`
Expected: 第一条 FAIL（现返 3），第二条 FAIL（默认 limit=5）。

- [ ] **Step 3: 改实现**

Edit `app/modules/im_intake/outbox_service.py`:

```python
def claim_batch(db: Session, user_id: int, limit: int = 1) -> list[IntakeOutbox]:
    """原子认领 pending outbox（→ claimed），返回给扩展去发送。

    **Hardened:** even if caller passes limit>1, we clamp to 1. Reason:
    2026-04-24 saw 3 outbox rows dispatch concurrently to a single Boss chat
    input, chars interleaved. Client-side mutex fixed it; this is the
    backend depth-defense so a misbehaving client cannot regress.

    Increments ``attempts`` at claim time (not at ack), so ``ack_failed`` in
    Task 5 just re-queues without touching the counter.
    """
    limit = max(1, min(1, int(limit)))  # hard clamp
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

- [ ] **Step 4: 同步 schema 默认值**

Find `OutboxClaimIn` in `app/modules/im_intake/schemas.py` and change default/max:

```python
class OutboxClaimIn(BaseModel):
    limit: int = Field(default=1, ge=1, le=1)  # hard capped; see outbox_service.claim_batch
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/modules/im_intake/test_outbox_concurrency.py -v`
Expected: 2 passed

- [ ] **Step 6: 运行已有 outbox 测试确保无 regression**

Run: `pytest tests/modules/im_intake/test_outbox_service.py -v`
Expected: 全 pass。

- [ ] **Step 7: 提交**

```bash
git add app/modules/im_intake/outbox_service.py app/modules/im_intake/schemas.py tests/modules/im_intake/test_outbox_concurrency.py
git commit -m "fix(f4): backend hard-cap outbox claim to limit=1

Defense in depth: even if a client requests limit=N, server clamps to 1
so concurrent dispatches cannot regress the content.js interleaving bug.
Extension alarm now effectively runs one outbox every 30s tick."
```

---

## Task 3: 迁移 0018 — `intake_user_settings` 表

**Files:**
- Create: `migrations/versions/0018_intake_user_settings.py`
- Create: `tests/modules/im_intake/test_migration_0018.py`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/im_intake/test_migration_0018.py`:

```python
"""Verify migration 0018 creates intake_user_settings and is reversible."""
from sqlalchemy import inspect

from tests.migration_utils import apply_upgrade, apply_downgrade, build_engine


def test_0018_upgrade_creates_table():
    engine = build_engine()
    apply_upgrade(engine, "0018")
    insp = inspect(engine)
    assert "intake_user_settings" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("intake_user_settings")}
    assert {"user_id", "enabled", "target_count", "created_at", "updated_at"} <= cols


def test_0018_downgrade_drops_table():
    engine = build_engine()
    apply_upgrade(engine, "0018")
    apply_downgrade(engine, "0017")
    insp = inspect(engine)
    assert "intake_user_settings" not in insp.get_table_names()
```

- [ ] **Step 2: 检查 migration_utils helpers 存在**

Run: `grep -n "apply_upgrade\|apply_downgrade\|build_engine" tests/migration_utils.py`
Expected: 3 helper 存在。若不存在，先看 `test_migration_0017.py` 照抄它用的辅助模式（可能直接 inline 了 Config + command.upgrade）。

If `tests/migration_utils.py` doesn't exist, inline the helpers in the new test file by copying the pattern from `tests/modules/im_intake/test_migration_0017.py`.

- [ ] **Step 3: 运行失败**

Run: `pytest tests/modules/im_intake/test_migration_0018.py -v`
Expected: FAIL — 迁移不存在。

- [ ] **Step 4: 写迁移**

Create `migrations/versions/0018_intake_user_settings.py`:

```python
"""F5 intake_user_settings: global target-count + pause/resume gate

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intake_user_settings',
        sa.Column('user_id', sa.Integer, primary_key=True),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('target_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
    )


def downgrade() -> None:
    op.drop_table('intake_user_settings')
```

- [ ] **Step 5: 本地升级 DB**

Run: `cd /d/0jingtong/AgenticHR && python -m alembic -c migrations/alembic.ini upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade 0017 -> 0018`

- [ ] **Step 6: 运行测试通过**

Run: `pytest tests/modules/im_intake/test_migration_0018.py -v`
Expected: 2 passed

- [ ] **Step 7: 提交**

```bash
git add migrations/versions/0018_intake_user_settings.py tests/modules/im_intake/test_migration_0018.py
git commit -m "feat(f5): migration 0018 intake_user_settings (target + enabled)"
```

---

## Task 4: `IntakeUserSettings` SQLAlchemy model

**Files:**
- Create: `app/modules/im_intake/settings_model.py`
- Test: 通过下一个 task 的 service 单测间接覆盖；单独再加一个 import/create 测试

- [ ] **Step 1: 写 model 文件**

Create `app/modules/im_intake/settings_model.py`:

```python
"""F5 per-user intake automation settings.

One row per user_id. `enabled` = master switch (start/pause).
`target_count` = desired number of `complete` candidates; once reached,
scheduler + autoscan + outbox claim all gate off until HR changes target
or resets counts.
"""
from sqlalchemy import Column, Integer, Boolean, DateTime, func
from app.database import Base


class IntakeUserSettings(Base):
    __tablename__ = "intake_user_settings"

    user_id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    target_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())
```

- [ ] **Step 2: 写 smoke 测试**

Create `tests/modules/im_intake/test_settings_model.py`:

```python
from app.modules.im_intake.settings_model import IntakeUserSettings


def test_model_fields_present():
    """Smoke: class imports and has the expected SQLAlchemy columns."""
    cols = {c.name for c in IntakeUserSettings.__table__.columns}
    assert cols == {"user_id", "enabled", "target_count", "created_at", "updated_at"}


def test_model_defaults(db_session):
    s = IntakeUserSettings(user_id=42)
    db_session.add(s); db_session.commit(); db_session.refresh(s)
    assert s.enabled is False
    assert s.target_count == 0
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/modules/im_intake/test_settings_model.py -v`
Expected: 2 passed

- [ ] **Step 4: 提交**

```bash
git add app/modules/im_intake/settings_model.py tests/modules/im_intake/test_settings_model.py
git commit -m "feat(f5): IntakeUserSettings ORM model"
```

---

## Task 5: `settings_service` — 获取/更新 + 达标/运行判定

**Files:**
- Create: `app/modules/im_intake/settings_service.py`
- Create: `tests/modules/im_intake/test_settings_service.py`

**API 要暴露：**
- `get_or_create(db, user_id) -> IntakeUserSettings`
- `update(db, user_id, *, enabled=None, target_count=None) -> IntakeUserSettings`
- `complete_count(db, user_id) -> int`
- `is_running(db, user_id) -> bool`  = `enabled AND complete_count < target_count`

- [ ] **Step 1: 写失败测试**

Create `tests/modules/im_intake/test_settings_service.py`:

```python
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.settings_service import (
    get_or_create, update, complete_count, is_running,
)


def test_get_or_create_returns_defaults(db_session):
    s = get_or_create(db_session, user_id=1)
    assert s.user_id == 1
    assert s.enabled is False
    assert s.target_count == 0


def test_get_or_create_is_idempotent(db_session):
    s1 = get_or_create(db_session, user_id=1)
    s2 = get_or_create(db_session, user_id=1)
    assert s1.user_id == s2.user_id  # same row


def test_update_partial_fields(db_session):
    get_or_create(db_session, user_id=1)
    s = update(db_session, user_id=1, enabled=True, target_count=50)
    assert s.enabled is True
    assert s.target_count == 50

    s2 = update(db_session, user_id=1, enabled=False)  # keeps target
    assert s2.enabled is False
    assert s2.target_count == 50


def test_complete_count_filters_by_user_and_status(db_session):
    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id="a", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="b", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="c", intake_status="collecting", source="plugin"),
        IntakeCandidate(user_id=2, boss_id="d", intake_status="complete", source="plugin"),
    ])
    db_session.commit()
    assert complete_count(db_session, user_id=1) == 2
    assert complete_count(db_session, user_id=2) == 1


def test_is_running_requires_enabled_and_under_target(db_session):
    get_or_create(db_session, user_id=1)
    assert is_running(db_session, user_id=1) is False  # disabled by default

    update(db_session, user_id=1, enabled=True, target_count=2)
    assert is_running(db_session, user_id=1) is True  # 0 complete < 2

    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id="x", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="y", intake_status="complete", source="plugin"),
    ])
    db_session.commit()
    assert is_running(db_session, user_id=1) is False  # 2 >= 2 → done


def test_is_running_zero_target_means_not_running(db_session):
    update(db_session, user_id=1, enabled=True, target_count=0)
    assert is_running(db_session, user_id=1) is False  # no target set = don't auto-run
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/modules/im_intake/test_settings_service.py -v`
Expected: ImportError（service 不存在）。

- [ ] **Step 3: 实现 service**

Create `app/modules/im_intake/settings_service.py`:

```python
"""F5 settings service — HR-facing master switch + target gate.

The scheduler, autoscan, and outbox claim all consult `is_running(db, user_id)`
before doing work. Semantics:
- enabled=False → HR paused; everything gates off
- enabled=True AND target_count==0 → not yet configured; gates off (safer
  default than "run forever")
- enabled=True AND complete_count >= target_count → done; gates off
"""
from sqlalchemy.orm import Session

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.settings_model import IntakeUserSettings


def get_or_create(db: Session, user_id: int) -> IntakeUserSettings:
    s = db.query(IntakeUserSettings).filter_by(user_id=user_id).first()
    if s is None:
        s = IntakeUserSettings(user_id=user_id, enabled=False, target_count=0)
        db.add(s); db.commit(); db.refresh(s)
    return s


def update(db: Session, user_id: int, *,
           enabled: bool | None = None,
           target_count: int | None = None) -> IntakeUserSettings:
    s = get_or_create(db, user_id)
    if enabled is not None:
        s.enabled = bool(enabled)
    if target_count is not None:
        if target_count < 0:
            raise ValueError("target_count must be >= 0")
        s.target_count = int(target_count)
    db.commit(); db.refresh(s)
    return s


def complete_count(db: Session, user_id: int) -> int:
    return (db.query(IntakeCandidate)
            .filter_by(user_id=user_id, intake_status="complete")
            .count())


def is_running(db: Session, user_id: int) -> bool:
    s = get_or_create(db, user_id)
    if not s.enabled:
        return False
    if s.target_count <= 0:
        return False
    return complete_count(db, user_id) < s.target_count
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/modules/im_intake/test_settings_service.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add app/modules/im_intake/settings_service.py tests/modules/im_intake/test_settings_service.py
git commit -m "feat(f5): settings_service with is_running / complete_count gate"
```

---

## Task 6: Settings HTTP API `GET/PUT /api/intake/settings`

**Files:**
- Modify: `app/modules/im_intake/router.py` — 加两个端点 + Pydantic schema
- Modify: `app/modules/im_intake/schemas.py` — 加 `IntakeSettingsOut` / `IntakeSettingsIn`
- Test: `tests/modules/im_intake/test_router_settings.py`（新建）

- [ ] **Step 1: 写失败测试**

Create `tests/modules/im_intake/test_router_settings.py`:

```python
"""HTTP API for /api/intake/settings."""
def test_get_settings_creates_defaults(auth_client):
    r = auth_client.get("/api/intake/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["target_count"] == 0
    assert body["complete_count"] == 0
    assert body["is_running"] is False


def test_put_settings_updates_fields(auth_client):
    r = auth_client.put("/api/intake/settings",
                        json={"enabled": True, "target_count": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["target_count"] == 50


def test_put_settings_rejects_negative_target(auth_client):
    r = auth_client.put("/api/intake/settings",
                        json={"target_count": -1})
    assert r.status_code == 422


def test_put_settings_partial_keeps_other_field(auth_client):
    auth_client.put("/api/intake/settings", json={"target_count": 30, "enabled": True})
    r = auth_client.put("/api/intake/settings", json={"enabled": False})
    body = r.json()
    assert body["enabled"] is False
    assert body["target_count"] == 30
```

- [ ] **Step 2: 确认 fixture `auth_client` 存在**

Run: `grep -rn "def auth_client" tests/conftest.py tests/ 2>/dev/null | head`
Expected: 至少一处 fixture 定义（与现有 router 测试一致）。

If no `auth_client` fixture exists, look at e.g. `tests/modules/im_intake/test_router.py` for the pattern used and copy its client-creation logic into the new test file (or into a local conftest).

- [ ] **Step 3: 确认测试失败**

Run: `pytest tests/modules/im_intake/test_router_settings.py -v`
Expected: 404s / AttributeError — 端点不存在。

- [ ] **Step 4: 加 schema**

Append to `app/modules/im_intake/schemas.py`:

```python
class IntakeSettingsOut(BaseModel):
    enabled: bool
    target_count: int = Field(ge=0)
    complete_count: int = Field(ge=0)
    is_running: bool


class IntakeSettingsIn(BaseModel):
    enabled: bool | None = None
    target_count: int | None = Field(default=None, ge=0)
```

- [ ] **Step 5: 加 router 端点**

Add to `app/modules/im_intake/router.py` (after the `/daily-cap` endpoint, before `/autoscan/rank`):

```python
from app.modules.im_intake.settings_service import (
    get_or_create as _settings_get_or_create,
    update as _settings_update,
    complete_count as _settings_complete_count,
    is_running as _settings_is_running,
)
from app.modules.im_intake.schemas import IntakeSettingsOut, IntakeSettingsIn


def _settings_response(db: Session, user_id: int) -> IntakeSettingsOut:
    s = _settings_get_or_create(db, user_id)
    return IntakeSettingsOut(
        enabled=s.enabled,
        target_count=s.target_count,
        complete_count=_settings_complete_count(db, user_id),
        is_running=_settings_is_running(db, user_id),
    )


@router.get("/settings", response_model=IntakeSettingsOut)
def get_intake_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return _settings_response(db, user_id)


@router.put("/settings", response_model=IntakeSettingsOut)
def put_intake_settings(
    body: IntakeSettingsIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    _settings_update(db, user_id,
                     enabled=body.enabled,
                     target_count=body.target_count)
    return _settings_response(db, user_id)
```

(Move imports to the file's top import block if they'd duplicate; keep the helper local.)

- [ ] **Step 6: 运行测试**

Run: `pytest tests/modules/im_intake/test_router_settings.py -v`
Expected: 4 passed

- [ ] **Step 7: 提交**

```bash
git add app/modules/im_intake/router.py app/modules/im_intake/schemas.py tests/modules/im_intake/test_router_settings.py
git commit -m "feat(f5): GET/PUT /api/intake/settings HTTP API"
```

---

## Task 7: Scheduler `scan_once` 前置 gate（按 user_id 分组 + 检查 is_running）

**Files:**
- Modify: `app/modules/im_intake/scheduler.py:scan_once`
- Test: `tests/modules/im_intake/test_scheduler_target_pause.py`（新建）

**当前问题：** `scan_once` 扫全局 `ACTIVE_CANDIDATE_STATES`，不分 user_id。必须 group by user_id，逐 user 检查 `is_running`，false 则跳过该 user 全部候选人。

- [ ] **Step 1: 写失败测试**

Create `tests/modules/im_intake/test_scheduler_target_pause.py`:

```python
"""F5 scan_once must respect per-user is_running gate."""
from datetime import datetime, timezone, timedelta

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.scheduler import scan_once
from app.modules.im_intake.settings_service import update as settings_update
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _mk_candidate_with_pending_slot(db, user_id: int, boss_id: str):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=boss_id,
        intake_status="collecting", source="plugin",
        intake_started_at=now, expires_at=now + timedelta(days=14),
    )
    db.add(c); db.flush()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def test_scan_once_skips_user_with_settings_disabled(db_session):
    _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="boss-1")
    settings_update(db_session, user_id=1, enabled=False, target_count=10)
    stats = scan_once(db_session)
    assert stats["seen"] == 0  # user 1 gated off
    assert stats["generated"] == 0


def test_scan_once_skips_user_who_reached_target(db_session):
    _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="boss-1")
    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id="c1", intake_status="complete", source="plugin"),
        IntakeCandidate(user_id=1, boss_id="c2", intake_status="complete", source="plugin"),
    ])
    db_session.commit()
    settings_update(db_session, user_id=1, enabled=True, target_count=2)
    stats = scan_once(db_session)
    assert stats["seen"] == 0  # target met


def test_scan_once_runs_for_user_below_target(db_session):
    c = _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="boss-1")
    settings_update(db_session, user_id=1, enabled=True, target_count=10)
    stats = scan_once(db_session)
    assert stats["seen"] == 1
    assert stats["generated"] == 1  # candidate had pending slot → send_hard outbox


def test_scan_once_isolates_users(db_session):
    """User 1 paused, user 2 running: only user 2 is scanned."""
    _mk_candidate_with_pending_slot(db_session, user_id=1, boss_id="b-1")
    _mk_candidate_with_pending_slot(db_session, user_id=2, boss_id="b-2")
    settings_update(db_session, user_id=1, enabled=False, target_count=5)
    settings_update(db_session, user_id=2, enabled=True, target_count=5)
    stats = scan_once(db_session)
    assert stats["seen"] == 1
```

- [ ] **Step 2: 确认失败**

Run: `pytest tests/modules/im_intake/test_scheduler_target_pause.py -v`
Expected: FAIL — 现 scan_once 不看 settings。

- [ ] **Step 3: 改 scheduler.scan_once**

Replace `scan_once` in `app/modules/im_intake/scheduler.py`:

```python
from app.modules.im_intake.settings_service import is_running as _settings_is_running


def scan_once(db: Session) -> dict[str, int]:
    """扫一次 active intake，生成 outbox；运行一次过期清理。返回统计。

    Per-user gate: for each distinct user_id with active candidates, skip the
    whole user if settings.is_running is False (paused OR target reached).
    Target/pause is the HR-facing master switch; cleanup + reap still run
    globally because they're corrections, not emissions.
    """
    generated = 0
    seen = 0
    hard_max = getattr(settings, "f4_hard_max_asks", 3)
    pdf_to = getattr(settings, "f4_pdf_timeout_hours", 72)
    cooldown = getattr(settings, "f4_ask_cooldown_hours", 6)

    active_user_ids = [row[0] for row in (
        db.query(IntakeCandidate.user_id)
        .filter(IntakeCandidate.intake_status.in_(ACTIVE_CANDIDATE_STATES))
        .distinct()
        .all()
    )]

    for uid in active_user_ids:
        if not _settings_is_running(db, uid):
            continue
        candidates = (db.query(IntakeCandidate)
                      .filter(IntakeCandidate.user_id == uid)
                      .filter(IntakeCandidate.intake_status.in_(ACTIVE_CANDIDATE_STATES))
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

    stale_min = getattr(settings, "f4_claim_stale_minutes", 10)
    reaped = reap_stale_claims(db, stale_minutes=stale_min)
    cleanup = cleanup_expired(db)
    return {"seen": seen, "generated": generated, "reaped": reaped, **cleanup}
```

- [ ] **Step 4: 运行新测试**

Run: `pytest tests/modules/im_intake/test_scheduler_target_pause.py -v`
Expected: 4 passed

- [ ] **Step 5: Regression — 跑现有 scheduler 测试**

Run: `pytest tests/modules/im_intake/ -v -k scheduler`
Expected: 无破坏（已有 test_scheduler.py 若存在应仍过）。

- [ ] **Step 6: 提交**

```bash
git add app/modules/im_intake/scheduler.py tests/modules/im_intake/test_scheduler_target_pause.py
git commit -m "feat(f5): scan_once gates per-user by is_running(target+enabled)"
```

---

## Task 8: Autoscan rank + outbox claim 加 gate

**Files:**
- Modify: `app/modules/im_intake/router.py` `/autoscan/rank` + `/outbox/claim`
- Test: `tests/modules/im_intake/test_router_settings.py`（追加测试）

**Why:** scheduler 只管生成 outbox。扩展两条轮询（autoscan tick 抓聊天、outbox poll 派消息）也必须在 paused / done 时空闲，否则暂停期间扩展继续派消息。

- [ ] **Step 1: 追加失败测试到 `test_router_settings.py`**

Append:

```python
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from datetime import datetime, timezone


def test_autoscan_rank_returns_empty_when_paused(auth_client, db_session, current_user_id):
    # Create one collecting candidate for this user
    db_session.add(IntakeCandidate(user_id=current_user_id, boss_id="z1",
                                   intake_status="collecting", source="plugin"))
    db_session.commit()
    # Disabled settings → no items
    auth_client.put("/api/intake/settings", json={"enabled": False, "target_count": 10})
    r = auth_client.get("/api/intake/autoscan/rank")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_autoscan_rank_returns_items_when_running(auth_client, db_session, current_user_id):
    db_session.add(IntakeCandidate(user_id=current_user_id, boss_id="z2",
                                   intake_status="collecting", source="plugin"))
    db_session.commit()
    auth_client.put("/api/intake/settings", json={"enabled": True, "target_count": 10})
    r = auth_client.get("/api/intake/autoscan/rank")
    assert len(r.json()["items"]) == 1


def test_outbox_claim_returns_empty_when_paused(auth_client, db_session, current_user_id):
    c = IntakeCandidate(user_id=current_user_id, boss_id="z3",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.flush()
    db_session.add(IntakeOutbox(candidate_id=c.id, user_id=current_user_id,
                                action_type="send_hard", text="hi",
                                slot_keys=[], status="pending",
                                scheduled_for=datetime.now(timezone.utc)))
    db_session.commit()
    auth_client.put("/api/intake/settings", json={"enabled": False, "target_count": 10})
    r = auth_client.post("/api/intake/outbox/claim", json={"limit": 1})
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_outbox_claim_returns_items_when_running(auth_client, db_session, current_user_id):
    c = IntakeCandidate(user_id=current_user_id, boss_id="z4",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.flush()
    db_session.add(IntakeOutbox(candidate_id=c.id, user_id=current_user_id,
                                action_type="send_hard", text="hi",
                                slot_keys=[], status="pending",
                                scheduled_for=datetime.now(timezone.utc)))
    db_session.commit()
    auth_client.put("/api/intake/settings", json={"enabled": True, "target_count": 10})
    r = auth_client.post("/api/intake/outbox/claim", json={"limit": 1})
    assert len(r.json()["items"]) == 1
```

If `current_user_id` fixture is missing, inline it: read the user_id the `auth_client` fixture authenticates as (grep `get_current_user_id` usage in existing router tests for the pattern).

- [ ] **Step 2: 确认失败**

Run: `pytest tests/modules/im_intake/test_router_settings.py -v`
Expected: 4 new FAIL（paused 仍返 items），2 其他仍 pass。

- [ ] **Step 3: 加 gate 到 `/autoscan/rank`**

In `app/modules/im_intake/router.py`, modify `autoscan_rank`:

```python
@router.get("/autoscan/rank")
def autoscan_rank(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Rank candidates most in need of an autoscan tick.

    Gated: returns [] when settings.is_running is False (paused or target met).
    """
    if not _settings_is_running(db, user_id):
        return {"items": []}
    rows = (
        db.query(IntakeCandidate)
        .filter(IntakeCandidate.user_id == user_id)
        .filter(IntakeCandidate.intake_status.in_(["collecting", "awaiting_reply"]))
        .order_by(
            case((IntakeCandidate.intake_status == "collecting", 0), else_=1),
            IntakeCandidate.updated_at.asc(),
        )
        .limit(limit)
        .all()
    )
    items = [
        {"candidate_id": c.id, "boss_id": c.boss_id, "name": c.name,
         "intake_status": c.intake_status,
         "last_activity_at": c.updated_at.isoformat() if c.updated_at else None}
        for c in rows
    ]
    return {"items": items}
```

- [ ] **Step 4: 加 gate 到 `/outbox/claim`**

```python
@router.post("/outbox/claim", response_model=OutboxClaimOut)
def outbox_claim(
    body: OutboxClaimIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if not _settings_is_running(db, user_id):
        return OutboxClaimOut(items=[])
    rows = _outbox_claim_batch(db, user_id=user_id, limit=body.limit)
    cand_ids = {r.candidate_id for r in rows}
    boss_by_cand: dict[int, str] = {}
    if cand_ids:
        boss_by_cand = dict(
            db.query(IntakeCandidate.id, IntakeCandidate.boss_id)
            .filter(IntakeCandidate.id.in_(cand_ids)).all()
        )
    return OutboxClaimOut(items=[
        OutboxClaimItem(
            id=r.id, candidate_id=r.candidate_id,
            boss_id=boss_by_cand.get(r.candidate_id, ""),
            action_type=r.action_type,
            text=r.text or "", slot_keys=r.slot_keys or [], attempts=r.attempts,
        ) for r in rows
    ])
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/modules/im_intake/test_router_settings.py -v`
Expected: 8 passed（原 4 + 新 4）。

- [ ] **Step 6: 提交**

```bash
git add app/modules/im_intake/router.py tests/modules/im_intake/test_router_settings.py
git commit -m "feat(f5): gate autoscan/rank + outbox/claim on is_running"
```

---

## Task 9: Frontend API client — `intakeSettings.js`

**Files:**
- Create: `frontend/src/api/intakeSettings.js`

- [ ] **Step 1: 写文件**

Create `frontend/src/api/intakeSettings.js`:

```javascript
import api from './index'

export const intakeSettingsApi = {
  getIntakeSettings: () => api.get('/intake/settings'),
  updateIntakeSettings: ({ enabled, target_count } = {}) => {
    const body = {}
    if (typeof enabled === 'boolean') body.enabled = enabled
    if (typeof target_count === 'number') body.target_count = target_count
    return api.put('/intake/settings', body)
  },
}

export const getIntakeSettings = intakeSettingsApi.getIntakeSettings
export const updateIntakeSettings = intakeSettingsApi.updateIntakeSettings

export default intakeSettingsApi
```

- [ ] **Step 2: Smoke typecheck / build**

Run: `cd frontend && pnpm typecheck` (或项目实际使用的 check 命令)
Expected: 无新错误。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/intakeSettings.js
git commit -m "feat(f5): frontend intakeSettings API client"
```

---

## Task 10: Frontend `/intake` 顶部卡片 — 目标 + 暂停按钮 + 进度

**Files:**
- Modify: `frontend/src/views/Intake.vue`

**UX：**
- 顶部新加一张 card（在 daily-cap 之前）
- 左侧：**目标候选人数** 数字输入框 + "保存" 按钮
- 中间：**进度条** `complete / target`（e.g. `3 / 50 (6%)`）
- 右侧：**开始 / 暂停** 大按钮（状态色：running=green，paused=gray，done=blue）
- 状态徽章："运行中 / 已暂停 / 已达标"

- [ ] **Step 1: 改模板加新 card**

Edit `frontend/src/views/Intake.vue` — 在 `<el-card shadow="never" class="daily-cap-card">` 之前插入新 card：

```vue
<el-card shadow="never" class="automation-card" style="margin-bottom: 12px">
  <div class="automation-row">
    <div class="automation-target">
      <span class="label">目标候选人数</span>
      <el-input-number v-model="settingsForm.target_count" :min="0" :max="1000" :step="5"
                       controls-position="right" style="width: 140px" />
      <el-button size="small" type="primary" @click="saveTarget" :loading="savingTarget">
        保存
      </el-button>
    </div>
    <div class="automation-progress">
      <el-progress :percentage="progressPercent" :stroke-width="12"
                   :status="progressStatus"
                   :format="() => `${settings.complete_count} / ${settings.target_count}`" />
    </div>
    <div class="automation-action">
      <el-tag :type="runningTagType" style="margin-right: 8px">{{ runningText }}</el-tag>
      <el-button v-if="settings.enabled" type="warning" @click="toggleEnabled(false)"
                 :loading="togglingEnabled">暂停</el-button>
      <el-button v-else type="success" @click="toggleEnabled(true)"
                 :loading="togglingEnabled">开始</el-button>
    </div>
  </div>
</el-card>
```

- [ ] **Step 2: 改 `<script setup>` 加 state + 方法**

Near the other `import` block:

```javascript
import { getIntakeSettings, updateIntakeSettings } from '../api/intakeSettings'
```

Near the other `ref()` declarations:

```javascript
const settings = ref({ enabled: false, target_count: 0, complete_count: 0, is_running: false })
const settingsForm = ref({ target_count: 0 })
const savingTarget = ref(false)
const togglingEnabled = ref(false)

const progressPercent = computed(() => {
  const t = settings.value.target_count
  if (!t) return 0
  return Math.min(100, Math.round((settings.value.complete_count / t) * 100))
})
const progressStatus = computed(() => {
  if (settings.value.target_count > 0 &&
      settings.value.complete_count >= settings.value.target_count) return 'success'
  return ''
})
const runningTagType = computed(() => {
  if (settings.value.is_running) return 'success'
  if (settings.value.target_count > 0 &&
      settings.value.complete_count >= settings.value.target_count) return 'info'
  return 'warning'
})
const runningText = computed(() => {
  if (settings.value.is_running) return '运行中'
  if (settings.value.target_count > 0 &&
      settings.value.complete_count >= settings.value.target_count) return '已达标'
  if (!settings.value.enabled) return '已暂停'
  return '未配置'
})

async function loadSettings() {
  try {
    const s = await getIntakeSettings()
    settings.value = s
    settingsForm.value.target_count = s.target_count
  } catch (e) {
    ElMessage.error('加载自动采集设置失败')
  }
}

async function saveTarget() {
  savingTarget.value = true
  try {
    const s = await updateIntakeSettings({ target_count: settingsForm.value.target_count })
    settings.value = s
    ElMessage.success('目标已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingTarget.value = false
  }
}

async function toggleEnabled(on) {
  if (on && settings.value.target_count <= 0) {
    ElMessage.warning('请先设置目标候选人数（>0）')
    return
  }
  togglingEnabled.value = true
  try {
    const s = await updateIntakeSettings({ enabled: on })
    settings.value = s
    ElMessage.success(on ? '已开始自动采集' : '已暂停')
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    togglingEnabled.value = false
  }
}
```

Modify `onMounted`:

```javascript
onMounted(() => {
  loadCandidates()
  loadDailyCap()
  loadSettings()
})
```

- [ ] **Step 3: 加样式（模板 `<style>` 块追加）**

```css
.automation-card .automation-row {
  display: flex;
  align-items: center;
  gap: 24px;
}
.automation-card .automation-target {
  display: flex; align-items: center; gap: 10px;
}
.automation-card .automation-target .label {
  font-size: 14px; color: #606266;
}
.automation-card .automation-progress {
  flex: 1;
}
.automation-card .automation-action {
  display: flex; align-items: center;
}
```

- [ ] **Step 4: 本地跑前端确保渲染**

Run: `cd frontend && pnpm dev`
Expected: 浏览器打开 `http://localhost:3000/intake`，顶部可见目标卡片 + 进度 0/0 + "开始" 按钮（灰色已暂停）。

- [ ] **Step 5: 手动 smoke**
1. 目标框输 3，点"保存" → toast "目标已保存"
2. 点"开始" → 按钮变"暂停"，徽章变绿"运行中"
3. 点"暂停" → 变回"开始"，徽章变黄"已暂停"
4. 刷新页面，设置持久化

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/Intake.vue
git commit -m "feat(f5): /intake target-count card + start/pause control"
```

---

## Task 11: Extension — backend settings 作为真相源

**Files:**
- Modify: `edge_extension/background.js` — 每个 alarm handler 前置 `fetchSettings`

**Why:** 前端设置 enabled=false 后，扩展继续跑 alarm 会打 API 只是拿空数组，但能早退省 API 调用。并且"目标已达标"也是 `is_running=false`，扩展应停 alarm。

- [ ] **Step 1: 加 `fetchIsRunning` helper**

Edit `edge_extension/background.js`, add near top (after storage reads):

```javascript
async function fetchIsRunning() {
  const { serverUrl, authToken } = await chrome.storage.local.get(["serverUrl", "authToken"]);
  if (!serverUrl || !authToken) return false;
  try {
    const r = await fetch(`${serverUrl}/api/intake/settings`, {
      headers: { "Authorization": `Bearer ${authToken}` },
    });
    if (!r.ok) return false;
    const s = await r.json();
    return !!s.is_running;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: 两个 alarm handler 前置检查**

In the `chrome.alarms.onAlarm.addListener`:

```javascript
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === INTAKE_ALARM_NAME) {
    if (!(await fetchIsRunning())) {
      console.log("[intake] autoscan tick skipped: backend is_running=false");
      return;
    }
    try {
      const tabs = await chrome.tabs.query({ url: "https://www.zhipin.com/*" });
      if (!tabs.length) {
        console.log("[intake] autoscan tick skipped: no Boss tab open");
        return;
      }
      const preferred = tabs.find((t) => /\/web\/chat(?!\/recommend)/.test(t.url || "")) || tabs[0];
      await chrome.tabs.sendMessage(preferred.id, { type: "intake_autoscan_tick", ts: Date.now() });
      console.log("[intake] autoscan tick sent to tab", preferred.id, preferred.url);
    } catch (e) {
      console.warn("[intake] autoscan tick failed:", e?.message || e);
    }
  } else if (alarm.name === OUTBOX_ALARM_NAME) {
    if (!(await fetchIsRunning())) return;
    await pollOutboxOnce();
  }
});
```

- [ ] **Step 3: 重载扩展手动 smoke**
1. Chrome `chrome://extensions` → 刷新扩展
2. 前端 `/intake` 设目标=3，点暂停
3. 等 30s，DevTools ServiceWorker console 看 `autoscan tick skipped: backend is_running=false`

- [ ] **Step 4: 提交**

```bash
git add edge_extension/background.js
git commit -m "feat(f5): extension alarms gate on backend is_running"
```

---

## Task 12: pytest 端到端 — 并发派发无交错

**Files:**
- Create: `tests/modules/im_intake/test_e2e_concurrency.py`

**Why:** content.js 串行 mutex 是 JS 运行时保护、无法在 pytest 里覆盖；但 **backend 层的保证**（claim 硬限 limit=1）可验证。这是回归锁。

- [ ] **Step 1: 写测试**

Create `tests/modules/im_intake/test_e2e_concurrency.py`:

```python
"""E2E concurrency regression: 3 pending outbox rows → 3 sequential claims,
each returns exactly 1. Never 2+ rows in a single response (would re-introduce
the 2026-04-24 char-interleaving bug if the extension had no mutex)."""
from datetime import datetime, timezone

import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.outbox_service import claim_batch, ack_sent
from app.modules.im_intake.settings_service import update as settings_update


@pytest.fixture
def three_pending_running(db_session):
    db = db_session
    settings_update(db, user_id=1, enabled=True, target_count=99)
    now = datetime.now(timezone.utc)
    for i in range(3):
        c = IntakeCandidate(user_id=1, boss_id=f"e2e-{i}", name=f"E{i}",
                            intake_status="collecting", source="plugin",
                            intake_started_at=now)
        db.add(c); db.flush()
        db.add(IntakeOutbox(candidate_id=c.id, user_id=1,
                            action_type="send_hard", text=f"Q{i}",
                            slot_keys=["arrival_date"],
                            status="pending", scheduled_for=now))
    db.commit()


def test_three_claims_return_one_each(db_session, three_pending_running):
    first = claim_batch(db_session, user_id=1, limit=5)
    second = claim_batch(db_session, user_id=1, limit=5)
    third = claim_batch(db_session, user_id=1, limit=5)
    fourth = claim_batch(db_session, user_id=1, limit=5)

    assert len(first) == 1
    assert len(second) == 1
    assert len(third) == 1
    assert len(fourth) == 0  # pool drained

    # All 3 distinct rows; no double-claim
    ids = {first[0].id, second[0].id, third[0].id}
    assert len(ids) == 3

    # All 3 are now in 'claimed' state, attempts=1
    for r in db_session.query(IntakeOutbox).all():
        assert r.status == "claimed"
        assert r.attempts == 1


def test_ack_success_transitions_to_sent_one_at_a_time(db_session, three_pending_running):
    first = claim_batch(db_session, user_id=1)
    ack_sent(db_session, first[0].id)
    assert db_session.query(IntakeOutbox).filter_by(id=first[0].id).first().status == "sent"

    # still 2 pending
    assert db_session.query(IntakeOutbox).filter_by(status="pending").count() == 2
```

- [ ] **Step 2: 运行**

Run: `pytest tests/modules/im_intake/test_e2e_concurrency.py -v`
Expected: 2 passed

- [ ] **Step 3: 提交**

```bash
git add tests/modules/im_intake/test_e2e_concurrency.py
git commit -m "test(f5): e2e regression for concurrent outbox dispatch"
```

---

## Task 13: pytest 端到端 — 达标自停 + 暂停生效完整链路

**Files:**
- Create: `tests/modules/im_intake/test_e2e_target_pause.py`

- [ ] **Step 1: 写测试**

Create `tests/modules/im_intake/test_e2e_target_pause.py`:

```python
"""E2E: target reached + pause both shut off all three surfaces
(scheduler scan_once, /autoscan/rank API, /outbox/claim API)."""
from datetime import datetime, timezone, timedelta

import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.scheduler import scan_once
from app.modules.im_intake.settings_service import update as settings_update
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.outbox_service import claim_batch


def _active_candidate(db, user_id, boss_id):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=user_id, boss_id=boss_id, name=boss_id,
                        intake_status="collecting", source="plugin",
                        intake_started_at=now, expires_at=now + timedelta(days=14))
    db.add(c); db.flush()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def _pending_outbox(db, c, user_id):
    now = datetime.now(timezone.utc)
    db.add(IntakeOutbox(candidate_id=c.id, user_id=user_id, action_type="send_hard",
                        text="Q", slot_keys=["arrival_date"], status="pending",
                        scheduled_for=now))
    db.commit()


def test_scheduler_stops_generating_when_target_met(db_session):
    c = _active_candidate(db_session, user_id=1, boss_id="t1")
    db_session.add_all([
        IntakeCandidate(user_id=1, boss_id=f"done-{i}", intake_status="complete",
                        source="plugin") for i in range(3)
    ])
    db_session.commit()
    settings_update(db_session, user_id=1, enabled=True, target_count=3)

    stats = scan_once(db_session)
    assert stats["generated"] == 0  # target met; no new outbox


def test_outbox_claim_empty_when_target_met(db_session):
    c = _active_candidate(db_session, user_id=1, boss_id="t2")
    _pending_outbox(db_session, c, user_id=1)
    db_session.add(IntakeCandidate(user_id=1, boss_id="done", intake_status="complete",
                                   source="plugin"))
    db_session.commit()
    settings_update(db_session, user_id=1, enabled=True, target_count=1)

    rows = claim_batch(db_session, user_id=1, limit=1)
    # Note: claim_batch itself doesn't gate; the gate is in the HTTP endpoint.
    # This test exercises the service; HTTP gate is covered in test_router_settings.
    assert len(rows) == 1  # claim_batch itself still returns rows
    # But scheduler would not GENERATE new rows past this point:
    stats = scan_once(db_session)
    assert stats["seen"] == 0


def test_full_pause_stops_everything(db_session):
    c = _active_candidate(db_session, user_id=1, boss_id="p1")
    _pending_outbox(db_session, c, user_id=1)
    settings_update(db_session, user_id=1, enabled=False, target_count=100)

    # Scheduler skips
    stats = scan_once(db_session)
    assert stats["seen"] == 0
    assert stats["generated"] == 0
    # Outbox row remains pending (nothing consumed)
    assert db_session.query(IntakeOutbox).filter_by(status="pending").count() == 1


def test_resume_re_runs_scheduler(db_session):
    c = _active_candidate(db_session, user_id=1, boss_id="r1")
    settings_update(db_session, user_id=1, enabled=False, target_count=10)
    assert scan_once(db_session)["seen"] == 0

    settings_update(db_session, user_id=1, enabled=True)
    stats = scan_once(db_session)
    assert stats["seen"] == 1  # ran after resume
```

- [ ] **Step 2: 运行**

Run: `pytest tests/modules/im_intake/test_e2e_target_pause.py -v`
Expected: 4 passed

- [ ] **Step 3: 全量测试跑一次**

Run: `pytest tests/modules/im_intake/ -v`
Expected: 全绿（包含所有前序 task 的测试）。

- [ ] **Step 4: 提交**

```bash
git add tests/modules/im_intake/test_e2e_target_pause.py
git commit -m "test(f5): e2e target-reached and pause-propagation"
```

---

## Task 14: 真实 E2E — backend + extension + Boss（AI 执行）

**Not a checkbox list — this is the acceptance gate AI runs after Tasks 1-13 land.**

**Files:** 无代码改动；只运行验证。

**前置：**
- Alembic upgrade 到 0018
- `F4_SCHEDULER_ENABLED=true`（重新启用，但受 settings gate 保护）
- 扩展重装/刷新
- `/intake` 页加载成功看到新卡片
- 浏览器登录 Boss 直聘

**Acceptance criteria（全部必须过，否则不算完成）：**

1. **UI 冒烟**
   - 打开 `/intake` → 顶部目标卡片渲染、显示当前值
   - 输入 target=3，保存 → 徽章显示"已暂停"（因 enabled=false 初始）
   - 点"开始" → 徽章变"运行中"、按钮变"暂停"
   - 后端 log 看到 scheduler `F4 scan: {seen: N, generated: M, ...}`
   - 扩展 service worker console 无 `skipped: is_running=false`

2. **并发不交错**
   - 构造 3 条 pending outbox（手 SQL insert 或跑 seed 脚本）
   - 观察 30s × 3 分钟：每条消息打进 Boss 输入框前**输入框必须是空的**，且发出的每条消息字符**连续无乱序**
   - Boss 聊天窗口截图附到 handoff

3. **达标自停**
   - target=2
   - 等候选人回复、槽位填满、自动晋级到 complete
   - 第 2 个 complete 出现后：扩展 service worker log 立刻显示 `skipped: is_running=false`（下一 tick 触发）
   - scheduler log 下一轮 `scan_once` 返回 seen=0
   - `/intake` 徽章变"已达标"

4. **暂停停手**
   - 运行中点"暂停"
   - 30s 内：扩展 service worker log 显示 `skipped`；后端 scheduler 下一轮 seen=0
   - DB `intake_outbox` 无新 pending 行

5. **恢复再跑**
   - 点"开始" → 下一轮 tick（≤30s）scheduler 开始扫，有 seen/generated 增长

6. **无 500 in collect-chat**
   - 连续 10 次 `/collect-chat` 调用（至少 3 次在 hard-slot 冷却期命中 `wait_reply` 分支）
   - 全部 200

**若任一 criterion 失败：**
- 定位根因
- 补测试 + 修代码 + 追加 task 到此 plan（e.g. Task 14.1）
- 重跑全 acceptance，直到 6 条全绿

**交付 artifact：**
- `docs/superpowers/reports/2026-04-24-f5-e2e-report.md` — 截图 + log 片段 + 结论
- 所有 commit merged 后更新 worktree 状态

---

## Self-Review

**Spec coverage:**
- ✅ "HR 输入一个数字" → Task 5 schema + 6 API + 10 UI
- ✅ "自动收集够指定数量停" → Task 7 scheduler gate + 8 claim/rank gate + 13 e2e
- ✅ "中间可以暂停和开启" → Task 6 PUT enabled + 10 UI button + 11 extension gate + 13 e2e
- ✅ "先修完并发 bug" → Task 1 commits local + 2 backend depth + 12 regression
- ✅ "实际真实测试直到无 bug" → Task 14 acceptance gate

**Placeholder scan:** None found. All code blocks concrete.

**Type consistency:** `is_running` / `complete_count` / `target_count` / `enabled` uniform across service (Task 5), API schema (Task 6), router helper (Task 6), frontend state (Task 10), extension helper (Task 11).

**Known deferral:** Job-level target (option B from brainstorm) explicitly descoped — A was chosen. If needed later, add `job_id` column to `intake_user_settings` with PK `(user_id, job_id)` and fan out the gate.
