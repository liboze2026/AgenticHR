# F4 Boss IM Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build automated candidate-info collector on Boss IM (`zhipin.com/web/chat/index`) that scans all conversations, fills 3 hard-must / PDF / soft-Q slots per candidate, batch-asks missing info without blocking, and admits complete candidates into `resumes` table — all without HITL.

**Architecture:** APScheduler job runs every 15 min → acquires single Playwright adapter lock → for up to 50 candidates, extracts existing slot values from chat history (regex first, LLM fallback), sends packed questions for missing slots, collects PDFs via "求简历" button + "已获取简历" tab, writes audit, transitions resume status to `passed` once complete (or `pending_human` if hard slots stuck after 3 asks, or `abandoned` if PDF missing >72h).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy + Alembic, Playwright (already configured), APScheduler, Pydantic v2, pytest + pytest-asyncio, Vue 3 + Element Plus.

---

## File Structure

**Create:**
- `migrations/versions/0011_f4_intake_slots.py` — Alembic migration
- `app/modules/im_intake/__init__.py`
- `app/modules/im_intake/models.py` — SQLAlchemy `IntakeSlot`
- `app/modules/im_intake/schemas.py` — Pydantic
- `app/modules/im_intake/templates.py` — hard-Q templates
- `app/modules/im_intake/slot_filler.py` — regex + LLM parser
- `app/modules/im_intake/question_generator.py` — hard templates + soft LLM
- `app/modules/im_intake/pdf_collector.py`
- `app/modules/im_intake/job_matcher.py`
- `app/modules/im_intake/service.py` — `IntakeService.process_one`
- `app/modules/im_intake/scheduler.py` — APScheduler + lock
- `app/modules/im_intake/router.py` — REST API
- `app/modules/im_intake/prompts/parse_v1.txt`
- `app/modules/im_intake/prompts/soft_question_v1.txt`
- `tests/modules/im_intake/__init__.py`
- `tests/modules/im_intake/conftest.py`
- `tests/modules/im_intake/test_migration_0011.py`
- `tests/modules/im_intake/test_models.py`
- `tests/modules/im_intake/test_slot_filler_regex.py`
- `tests/modules/im_intake/test_slot_filler_llm.py`
- `tests/modules/im_intake/test_question_generator.py`
- `tests/modules/im_intake/test_pdf_collector.py`
- `tests/modules/im_intake/test_job_matcher.py`
- `tests/modules/im_intake/test_service_pipeline.py`
- `tests/modules/im_intake/test_scheduler_lock.py`
- `tests/modules/im_intake/test_router.py`
- `tests/modules/im_intake/test_pending_human.py`
- `tests/modules/im_intake/test_abandoned.py`
- `tests/adapters/boss/test_playwright_chat_index.py`
- `frontend/src/views/Intake.vue`
- `frontend/src/api/intake.js`

**Modify:**
- `app/adapters/boss/playwright_adapter.py` — add `list_chat_index`, `send_message`, `click_request_resume`, `list_received_resumes`
- `app/adapters/boss/base.py` — extend interface
- `app/modules/resume/models.py` — add `intake_status`, `intake_started_at`, `intake_completed_at`, `job_id`
- `app/main.py` — register intake router + start scheduler
- `app/config.py` — add F4 env settings
- `frontend/src/router/index.js` — add `/intake` route
- `frontend/src/views/Dashboard.vue` (or main nav file) — add nav link
- `CHANGELOG.md`

---

## Task 1: Alembic migration 0011 — intake_slots + Resume fields

**Files:**
- Create: `migrations/versions/0011_f4_intake_slots.py`
- Test: `tests/modules/im_intake/test_migration_0011.py`

- [ ] **Step 1: Write failing migration test**

```python
# tests/modules/im_intake/test_migration_0011.py
import pytest
from sqlalchemy import inspect, text
from app.database import engine, Base

def test_intake_slots_table_exists():
    insp = inspect(engine)
    assert "intake_slots" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("intake_slots")}
    assert {"id", "resume_id", "slot_key", "slot_category", "value",
            "asked_at", "answered_at", "ask_count", "last_ask_text",
            "source", "question_meta", "created_at", "updated_at"}.issubset(cols)

def test_intake_slots_unique_resume_key():
    insp = inspect(engine)
    idxs = insp.get_indexes("intake_slots")
    uq = [i for i in idxs if i.get("unique") and set(i["column_names"]) == {"resume_id", "slot_key"}]
    assert len(uq) == 1, f"expected unique(resume_id, slot_key), got {idxs}"

def test_resumes_intake_columns():
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("resumes")}
    assert {"intake_status", "intake_started_at", "intake_completed_at", "job_id"}.issubset(cols)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/modules/im_intake/test_migration_0011.py -v`
Expected: FAIL — `intake_slots` not in tables.

- [ ] **Step 3: Write migration**

```python
# migrations/versions/0011_f4_intake_slots.py
"""F4 intake_slots table + resumes.intake_* fields

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'intake_slots',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('resume_id', sa.Integer, nullable=False),
        sa.Column('slot_key', sa.String(64), nullable=False),
        sa.Column('slot_category', sa.String(16), nullable=False),
        sa.Column('value', sa.Text, nullable=True),
        sa.Column('asked_at', sa.DateTime, nullable=True),
        sa.Column('answered_at', sa.DateTime, nullable=True),
        sa.Column('ask_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_ask_text', sa.Text, nullable=True),
        sa.Column('source', sa.String(32), nullable=True),
        sa.Column('question_meta', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='CASCADE'),
    )
    op.create_index('uq_intake_resume_slot', 'intake_slots', ['resume_id', 'slot_key'], unique=True)
    op.create_index('idx_intake_resume', 'intake_slots', ['resume_id'])
    op.create_index('idx_intake_answered', 'intake_slots', ['answered_at'])

    with op.batch_alter_table('resumes') as batch_op:
        batch_op.add_column(sa.Column('intake_status', sa.String(20), nullable=False, server_default='collecting'))
        batch_op.add_column(sa.Column('intake_started_at', sa.DateTime, nullable=True))
        batch_op.add_column(sa.Column('intake_completed_at', sa.DateTime, nullable=True))
        batch_op.add_column(sa.Column('job_id', sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('resumes') as batch_op:
        batch_op.drop_column('job_id')
        batch_op.drop_column('intake_completed_at')
        batch_op.drop_column('intake_started_at')
        batch_op.drop_column('intake_status')
    op.drop_index('idx_intake_answered', table_name='intake_slots')
    op.drop_index('idx_intake_resume', table_name='intake_slots')
    op.drop_index('uq_intake_resume_slot', table_name='intake_slots')
    op.drop_table('intake_slots')
```

- [ ] **Step 4: Run migration + test**

Run: `alembic upgrade head && pytest tests/modules/im_intake/test_migration_0011.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/0011_f4_intake_slots.py tests/modules/im_intake/__init__.py tests/modules/im_intake/test_migration_0011.py
git commit -m "feat(f4-T1): alembic 0011 — intake_slots + resumes.intake_* fields"
```

---

## Task 2: SQLAlchemy IntakeSlot model + Resume field bindings

**Files:**
- Create: `app/modules/im_intake/__init__.py`, `app/modules/im_intake/models.py`
- Modify: `app/modules/resume/models.py`
- Test: `tests/modules/im_intake/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_models.py
from datetime import datetime, timezone
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume

def test_intake_slot_create_and_query(db_session):
    r = Resume(name="张三", boss_id="abc", intake_status="collecting")
    db_session.add(r); db_session.commit()
    s = IntakeSlot(
        resume_id=r.id, slot_key="arrival_date", slot_category="hard",
        value="下周一", source="regex",
        asked_at=datetime.now(timezone.utc), answered_at=datetime.now(timezone.utc),
        ask_count=1,
    )
    db_session.add(s); db_session.commit()
    assert IntakeSlot.__tablename__ == "intake_slots"
    rows = db_session.query(IntakeSlot).filter_by(resume_id=r.id).all()
    assert len(rows) == 1 and rows[0].slot_key == "arrival_date"

def test_resume_has_intake_fields():
    cols = Resume.__table__.columns.keys()
    for c in ("intake_status", "intake_started_at", "intake_completed_at", "job_id"):
        assert c in cols, f"missing {c}"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/modules/im_intake/test_models.py -v`
Expected: FAIL — `app.modules.im_intake.models` not importable.

- [ ] **Step 3: Implement model**

```python
# app/modules/im_intake/__init__.py
```

```python
# app/modules/im_intake/models.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from app.database import Base


class IntakeSlot(Base):
    __tablename__ = "intake_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    slot_key = Column(String(64), nullable=False)
    slot_category = Column(String(16), nullable=False)
    value = Column(Text, nullable=True)
    asked_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    ask_count = Column(Integer, nullable=False, default=0)
    last_ask_text = Column(Text, nullable=True)
    source = Column(String(32), nullable=True)
    question_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

Add to `app/modules/resume/models.py` (after the `greeted_at` column, before `created_at`):

```python
    intake_status = Column(String(20), default="collecting", nullable=False)
    intake_started_at = Column(DateTime, nullable=True)
    intake_completed_at = Column(DateTime, nullable=True)
    job_id = Column(Integer, nullable=True)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/ app/modules/resume/models.py tests/modules/im_intake/test_models.py
git commit -m "feat(f4-T2): IntakeSlot model + Resume.intake_* mappings"
```

---

## Task 3: Pydantic schemas

**Files:**
- Create: `app/modules/im_intake/schemas.py`
- Test: `tests/modules/im_intake/test_schemas.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_schemas.py
from datetime import datetime
from app.modules.im_intake.schemas import (
    SlotOut, CandidateOut, CandidateDetailOut, SlotPatchIn,
    SchedulerStatus,
)

def test_slot_out_round_trip():
    s = SlotOut(id=1, slot_key="arrival_date", slot_category="hard",
                value="下周一", ask_count=1, asked_at=datetime(2026,4,22),
                answered_at=datetime(2026,4,22), source="regex",
                last_ask_text="您好~", question_meta=None)
    assert s.slot_key == "arrival_date"

def test_slot_patch_requires_value():
    p = SlotPatchIn(value="下周三")
    assert p.value == "下周三"

def test_scheduler_status_fields():
    s = SchedulerStatus(
        running=True, next_run_at=None,
        daily_cap_used=10, daily_cap_max=1000,
        last_batch_size=5,
    )
    assert s.daily_cap_max == 1000
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_schemas.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement schemas**

```python
# app/modules/im_intake/schemas.py
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


SlotKey = str
SlotCategory = Literal["hard", "pdf", "soft"]
IntakeStatus = Literal["collecting", "awaiting_reply", "pending_human", "complete", "abandoned"]


class SlotOut(BaseModel):
    id: int
    slot_key: SlotKey
    slot_category: SlotCategory
    value: str | None = None
    ask_count: int = 0
    asked_at: datetime | None = None
    answered_at: datetime | None = None
    last_ask_text: str | None = None
    source: str | None = None
    question_meta: dict | None = None


class CandidateOut(BaseModel):
    resume_id: int
    boss_id: str
    name: str
    job_id: int | None = None
    job_title: str = ""
    intake_status: IntakeStatus
    progress_done: int
    progress_total: int
    last_activity_at: datetime | None = None


class CandidateDetailOut(CandidateOut):
    slots: list[SlotOut]


class SlotPatchIn(BaseModel):
    value: str = Field(min_length=1)


class SchedulerStatus(BaseModel):
    running: bool
    next_run_at: datetime | None = None
    daily_cap_used: int
    daily_cap_max: int
    last_batch_size: int
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_schemas.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/schemas.py tests/modules/im_intake/test_schemas.py
git commit -m "feat(f4-T3): pydantic schemas for intake API"
```

---

## Task 4: Hard-question templates

**Files:**
- Create: `app/modules/im_intake/templates.py`
- Test: extend `tests/modules/im_intake/test_question_generator.py` (created in T6)

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_templates.py
from app.modules.im_intake.templates import HARD_QUESTIONS, get_hard_question

def test_three_keys_three_variants():
    for k in ("arrival_date", "free_slots", "intern_duration"):
        assert k in HARD_QUESTIONS
        assert len(HARD_QUESTIONS[k]) == 3

def test_get_hard_question_by_count():
    q0 = get_hard_question("arrival_date", 0)
    q1 = get_hard_question("arrival_date", 1)
    q2 = get_hard_question("arrival_date", 2)
    assert q0 != q1 != q2
    assert "到岗" in q0 or "入职" in q0

def test_get_hard_question_clamps():
    assert get_hard_question("arrival_date", 99) == get_hard_question("arrival_date", 2)
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_templates.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement templates**

```python
# app/modules/im_intake/templates.py
HARD_QUESTIONS: dict[str, list[str]] = {
    "arrival_date": [
        "您好~请问您最快什么时候可以到岗呢？",
        "想再确认一下您的入职时间方便告知吗？",
        "麻烦最后确认下到岗时间哦~",
    ],
    "free_slots": [
        "方便告知您接下来五天哪些时段可以面试吗？",
        "想约下面试时间，您这周哪些时段方便？",
        "最后确认下，您这五天内可面试的具体时段~",
    ],
    "intern_duration": [
        "请问您实习能持续多久呢？",
        "想再确认下您可以实习的总时长~",
        "麻烦最后确认下实习时长哦~",
    ],
}

HARD_SLOT_KEYS = ("arrival_date", "free_slots", "intern_duration")


def get_hard_question(slot_key: str, ask_count: int) -> str:
    variants = HARD_QUESTIONS[slot_key]
    return variants[min(ask_count, len(variants) - 1)]
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_templates.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/templates.py tests/modules/im_intake/test_templates.py
git commit -m "feat(f4-T4): hard-question templates with 3 variants per slot"
```

---

## Task 5: SlotFiller — regex layer (golden set)

**Files:**
- Create: `app/modules/im_intake/slot_filler.py`
- Test: `tests/modules/im_intake/test_slot_filler_regex.py`

- [ ] **Step 1: Write failing test (golden set 50 cases)**

```python
# tests/modules/im_intake/test_slot_filler_regex.py
import pytest
from app.modules.im_intake.slot_filler import regex_extract

ARRIVAL_CASES = [
    ("我下周一可以入职", "下周一"),
    ("立刻就能到岗", "立刻"),
    ("4月28号开始", "4月28号"),
    ("随时", "随时"),
    ("明天就行", "明天"),
    ("周一", "周一"),
    ("下周三入职", "下周三"),
    ("5月1日", "5月1日"),
    ("后天到岗", "后天"),
    ("马上就可以", "马上"),
    ("4月30日开始上班", "4月30日"),
    ("下下周也可以", None),
    ("还要一段时间", None),
    ("看公司安排", None),
    ("现在就行", None),
]

INTERN_CASES = [
    ("可以实习6个月", "6个月"),
    ("3个月没问题", "3个月"),
    ("半年", "半年"),
    ("一年", "一年"),
    ("长期", "长期"),
    ("实习12个月", "12个月"),
    ("4 个月", "4个月"),
    ("两个月", None),
    ("看情况", None),
    ("不确定", None),
]

FREE_CASES = [
    ("周二下午、周四上午", ["周二下午", "周四上午"]),
    ("周一上午", ["周一上午"]),
    ("周三晚上有空", ["周三晚上"]),
    ("周一周二都行", ["周一", "周二"]),
    ("下午都可以", []),
    ("没空", []),
]

@pytest.mark.parametrize("text,expected", ARRIVAL_CASES)
def test_arrival_date(text, expected):
    assert regex_extract("arrival_date", text) == expected

@pytest.mark.parametrize("text,expected", INTERN_CASES)
def test_intern_duration(text, expected):
    assert regex_extract("intern_duration", text) == expected

@pytest.mark.parametrize("text,expected", FREE_CASES)
def test_free_slots(text, expected):
    assert regex_extract("free_slots", text) == expected
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_slot_filler_regex.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement regex layer**

```python
# app/modules/im_intake/slot_filler.py
import re
from typing import Any

ARRIVAL_PATTERNS = [
    re.compile(r"(下周[一二三四五六日天])"),
    re.compile(r"(明天|后天|立刻|马上|随时)"),
    re.compile(r"(\d+月\d+[号日])"),
    re.compile(r"^(周[一二三四五六日天])$"),
]

INTERN_PATTERN = re.compile(r"(\d+\s*个?\s*月|半年|一年|长期)")
INTERN_NORMALIZE = re.compile(r"(\d+)\s*个?\s*月")

FREE_PATTERN = re.compile(r"(周[一二三四五六日天])\s*(上午|下午|晚上)?")


def _arrival(text: str) -> str | None:
    for pat in ARRIVAL_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _intern(text: str) -> str | None:
    m = INTERN_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1)
    nm = INTERN_NORMALIZE.match(raw)
    if nm:
        return f"{nm.group(1)}个月"
    return raw


def _free(text: str) -> list[str]:
    out: list[str] = []
    for m in FREE_PATTERN.finditer(text):
        day, period = m.group(1), m.group(2) or ""
        out.append(f"{day}{period}")
    return out


def regex_extract(slot_key: str, text: str) -> Any:
    if slot_key == "arrival_date":
        return _arrival(text)
    if slot_key == "intern_duration":
        return _intern(text)
    if slot_key == "free_slots":
        return _free(text)
    return None
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_slot_filler_regex.py -v`
Expected: PASS (31 cases). If any fail, refine regex until all pass before committing.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/slot_filler.py tests/modules/im_intake/test_slot_filler_regex.py
git commit -m "feat(f4-T5): regex slot extractor with 31-case golden set"
```

---

## Task 6: SlotFiller — LLM fallback layer

**Files:**
- Modify: `app/modules/im_intake/slot_filler.py`
- Create: `app/modules/im_intake/prompts/parse_v1.txt`
- Test: `tests/modules/im_intake/test_slot_filler_llm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_slot_filler_llm.py
import json
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.slot_filler import SlotFiller


@pytest.mark.asyncio
async def test_llm_called_when_regex_misses():
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "arrival_date": "下周二",
        "intern_duration": None,
        "free_slots": [],
    })
    f = SlotFiller(llm=llm)
    result = await f.parse_reply(
        reply_text="可能下周二吧",
        pending_slot_keys=["arrival_date", "intern_duration", "free_slots"],
    )
    llm.complete.assert_called_once()
    assert result["arrival_date"] == ("下周二", "llm")
    assert "intern_duration" not in result
    assert "free_slots" not in result


@pytest.mark.asyncio
async def test_regex_short_circuits_llm():
    llm = AsyncMock()
    f = SlotFiller(llm=llm)
    result = await f.parse_reply("我下周一入职", pending_slot_keys=["arrival_date"])
    llm.complete.assert_not_called()
    assert result["arrival_date"] == ("下周一", "regex")


@pytest.mark.asyncio
async def test_llm_invalid_json_returns_empty():
    llm = AsyncMock()
    llm.complete.return_value = "not json"
    f = SlotFiller(llm=llm)
    result = await f.parse_reply("乱说", pending_slot_keys=["arrival_date"])
    assert result == {}
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_slot_filler_llm.py -v`
Expected: FAIL — `SlotFiller` class missing.

- [ ] **Step 3: Implement prompt + class**

```
# app/modules/im_intake/prompts/parse_v1.txt
你是招聘信息抽取助手。从候选人下面的回复中抽取以下字段，未提到则置 null。
回复："""{reply}"""

需要抽取的字段：{pending_keys}
- arrival_date: 候选人最快到岗时间，原文片段（如 "下周一" "4月28号"），未提及为 null
- intern_duration: 实习可持续时长，原文片段（如 "6个月" "半年"），未提及为 null
- free_slots: 接下来5天可面试时段数组（如 ["周二下午"]），未提及为 []

只输出 JSON，无其他文字。
```

Append to `app/modules/im_intake/slot_filler.py`:

```python
import json
from pathlib import Path
from typing import Protocol

PROMPT_PARSE = (Path(__file__).parent / "prompts" / "parse_v1.txt").read_text(encoding="utf-8")


class LLMLike(Protocol):
    async def complete(self, messages: list[dict], response_format: str = "json", **kw) -> str: ...


class SlotFiller:
    def __init__(self, llm: LLMLike | None = None):
        self.llm = llm

    async def parse_reply(self, reply_text: str, pending_slot_keys: list[str]) -> dict[str, tuple]:
        result: dict[str, tuple] = {}
        unresolved: list[str] = []
        for key in pending_slot_keys:
            val = regex_extract(key, reply_text)
            if val not in (None, []):
                result[key] = (val, "regex")
            else:
                unresolved.append(key)

        if not unresolved or self.llm is None:
            return result

        prompt = PROMPT_PARSE.format(reply=reply_text, pending_keys=unresolved)
        try:
            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format="json",
                temperature=0.1,
                prompt_version="parse_v1",
            )
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return result

        for key in unresolved:
            v = data.get(key)
            if v in (None, "", []):
                continue
            result[key] = (v, "llm")
        return result
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_slot_filler_llm.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/slot_filler.py app/modules/im_intake/prompts/parse_v1.txt tests/modules/im_intake/test_slot_filler_llm.py
git commit -m "feat(f4-T6): SlotFiller LLM fallback with JSON parsing + safe failure"
```

---

## Task 7: QuestionGenerator — hard packing + soft LLM

**Files:**
- Create: `app/modules/im_intake/question_generator.py`, `app/modules/im_intake/prompts/soft_question_v1.txt`
- Test: `tests/modules/im_intake/test_question_generator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_question_generator.py
import json
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.question_generator import QuestionGenerator


def test_pack_hard_first_round():
    qg = QuestionGenerator(llm=None)
    text = qg.pack_hard(
        candidate_name="张三", job_title="前端开发",
        missing=[("arrival_date", 0), ("free_slots", 0), ("intern_duration", 0)],
    )
    assert "张三" in text and "前端开发" in text
    assert "到岗" in text or "入职" in text
    assert "面试" in text
    assert "实习" in text
    assert text.endswith("[AI 助手]")


def test_pack_hard_repeat_uses_variant():
    qg = QuestionGenerator(llm=None)
    t0 = qg.pack_hard("张三", "前端", [("arrival_date", 0)])
    t1 = qg.pack_hard("张三", "前端", [("arrival_date", 1)])
    assert t0 != t1


@pytest.mark.asyncio
async def test_soft_questions_via_llm():
    llm = AsyncMock()
    llm.complete.return_value = json.dumps([
        {"dimension_id": "d1", "dimension_name": "系统设计", "question": "讲讲你的秒杀系统？"},
    ])
    qg = QuestionGenerator(llm=llm)
    out = await qg.generate_soft(
        dimensions=[{"id": "d1", "name": "系统设计", "description": "..."}],
        resume_summary="做过电商秒杀",
        max_n=3,
    )
    assert len(out) == 1
    assert out[0]["question"] == "讲讲你的秒杀系统？"
    assert out[0]["dimension_id"] == "d1"


def test_pack_soft_appends_label():
    qg = QuestionGenerator(llm=None)
    text = qg.pack_soft([
        {"dimension_id": "d1", "dimension_name": "系统设计", "question": "讲讲秒杀？"},
    ])
    assert "讲讲秒杀？" in text
    assert text.endswith("[AI 助手]")
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_question_generator.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement prompt + generator**

```
# app/modules/im_intake/prompts/soft_question_v1.txt
你是资深 HR 面试官。基于下面的考察维度和候选人简历摘要，生成最多 {max_n} 个针对性的简短问题，
用于在 IM 中初步了解候选人。要求：
- 每题 ≤ 60 字
- 优先针对简历里出现的项目/技能
- 不得使用任何性别、年龄、地域、院校歧视性表达
- 输出 JSON 数组：[{{"dimension_id": "...", "dimension_name": "...", "question": "..."}}]

考察维度：{dimensions}
简历摘要：{resume_summary}

只输出 JSON 数组，无其他文字。
```

```python
# app/modules/im_intake/question_generator.py
import json
from pathlib import Path
from typing import Protocol
from app.modules.im_intake.templates import get_hard_question

LABEL = "[AI 助手]"
PROMPT_SOFT = (Path(__file__).parent / "prompts" / "soft_question_v1.txt").read_text(encoding="utf-8")


class LLMLike(Protocol):
    async def complete(self, messages: list[dict], response_format: str = "json", **kw) -> str: ...


class QuestionGenerator:
    def __init__(self, llm: LLMLike | None = None):
        self.llm = llm

    def pack_hard(self, candidate_name: str, job_title: str, missing: list[tuple[str, int]]) -> str:
        lines = [f"您好{candidate_name}~"]
        if job_title:
            lines.append(f"我们对接的是【{job_title}】岗位，想跟您先确认几个信息：")
        else:
            lines.append("想跟您先确认几个信息：")
        for i, (key, count) in enumerate(missing, 1):
            lines.append(f"{i}. {get_hard_question(key, count)}")
        lines.append(LABEL)
        return "\n".join(lines)

    async def generate_soft(self, dimensions: list[dict], resume_summary: str, max_n: int = 3) -> list[dict]:
        if self.llm is None or not dimensions:
            return []
        prompt = PROMPT_SOFT.format(
            max_n=max_n,
            dimensions=json.dumps(dimensions, ensure_ascii=False),
            resume_summary=resume_summary[:2000],
        )
        try:
            raw = await self.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format="json",
                temperature=0.4,
                prompt_version="soft_question_v1",
            )
            data = json.loads(raw)
            return [d for d in data if d.get("question")][:max_n]
        except Exception:
            return []

    def pack_soft(self, questions: list[dict]) -> str:
        if not questions:
            return ""
        lines = ["想再了解一下："]
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q['question']}")
        lines.append(LABEL)
        return "\n".join(lines)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_question_generator.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/question_generator.py app/modules/im_intake/prompts/soft_question_v1.txt tests/modules/im_intake/test_question_generator.py
git commit -m "feat(f4-T7): QuestionGenerator — hard packing + soft LLM with [AI 助手] label"
```

---

## Task 8: PlaywrightBossAdapter extensions

**Files:**
- Modify: `app/adapters/boss/base.py`, `app/adapters/boss/playwright_adapter.py`
- Test: `tests/adapters/boss/test_playwright_chat_index.py`

- [ ] **Step 1: Write failing test (mock Page)**

```python
# tests/adapters/boss/test_playwright_chat_index.py
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.adapters.boss.playwright_adapter import PlaywrightBossAdapter


def _mock_item(name, data_id, job=""):
    item = AsyncMock()
    name_el = AsyncMock(); name_el.inner_text = AsyncMock(return_value=name)
    job_el = AsyncMock(); job_el.inner_text = AsyncMock(return_value=job)
    item.query_selector.side_effect = lambda sel: {
        ".geek-name": name_el, ".source-job": job_el,
    }.get(sel)
    item.get_attribute = AsyncMock(return_value=data_id)
    return item


@pytest.mark.asyncio
async def test_list_chat_index_iterates_all_tabs():
    a = PlaywrightBossAdapter()
    page = AsyncMock()
    page.query_selector_all = AsyncMock(side_effect=[
        [_mock_item("张三", "id1", "前端"), _mock_item("李四", "id2", "后端")],
    ])
    page.goto = AsyncMock(); page.wait_for_selector = AsyncMock()
    a._page = page; a._random_delay = AsyncMock()
    a._switch_tab = AsyncMock(return_value=True)

    out = await a.list_chat_index()

    assert len(out) == 2
    assert out[0].boss_id == "id1" and out[0].name == "张三"
    a._switch_tab.assert_called_with("全部")


@pytest.mark.asyncio
async def test_send_message_types_and_clicks_send():
    a = PlaywrightBossAdapter()
    page = AsyncMock()
    input_el = AsyncMock(); send_btn = AsyncMock()
    page.query_selector = AsyncMock(side_effect=lambda sel: {
        f'.geek-item[data-id="bx"]': AsyncMock(),
        '#boss-chat-editor-input': input_el,
        '.submit-content .submit': send_btn,
    }.get(sel))
    page.wait_for_selector = AsyncMock()
    page.keyboard = MagicMock(); page.keyboard.type = AsyncMock()
    a._page = page; a._random_delay = AsyncMock()
    a._human_click = AsyncMock(); a._operations_today = 0

    ok = await a.send_message("bx", "你好")

    assert ok is True
    assert a._operations_today == 1
    send_btn.click.assert_called_once()


@pytest.mark.asyncio
async def test_list_received_resumes_returns_pdf_pairs():
    a = PlaywrightBossAdapter()
    page = AsyncMock()
    card = AsyncMock()
    card.get_attribute = AsyncMock(return_value="id99")
    btn = AsyncMock(); btn.get_attribute = AsyncMock(return_value="https://x/y.pdf")
    card.query_selector = AsyncMock(return_value=btn)
    page.query_selector_all = AsyncMock(return_value=[card])
    page.goto = AsyncMock()
    a._page = page; a._random_delay = AsyncMock()
    a._switch_tab = AsyncMock(return_value=True)

    out = await a.list_received_resumes()

    assert out == [("id99", "https://x/y.pdf")]
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/adapters/boss/test_playwright_chat_index.py -v`
Expected: FAIL — methods missing.

- [ ] **Step 3: Implement adapter extensions**

Add to `app/adapters/boss/base.py` (inside `BossAdapter` ABC):

```python
    @abstractmethod
    async def list_chat_index(self) -> list[BossCandidate]:
        """切到 chat/index '全部' tab，扫所有对话条目"""
        ...

    @abstractmethod
    async def send_message(self, boss_id: str, text: str) -> bool:
        """对指定候选人发送普通文字消息"""
        ...

    @abstractmethod
    async def click_request_resume(self, boss_id: str) -> bool:
        """点求简历按钮"""
        ...

    @abstractmethod
    async def list_received_resumes(self) -> list[tuple[str, str]]:
        """扫已获取简历 tab → [(boss_id, pdf_url)]"""
        ...
```

Add methods to `app/adapters/boss/playwright_adapter.py` (after `is_available`):

```python
    async def list_chat_index(self) -> list[BossCandidate]:
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        await self._page.goto(self.CHAT_URL, wait_until="networkidle")
        await self._random_delay()
        await self._switch_tab("全部")

        out: list[BossCandidate] = []
        items = await self._page.query_selector_all(".geek-item")
        for item in items:
            name_el = await item.query_selector(".geek-name")
            name = await name_el.inner_text() if name_el else ""
            job_el = await item.query_selector(".source-job")
            job = await job_el.inner_text() if job_el else ""
            data_id = await item.get_attribute("data-id") or ""
            if name:
                out.append(BossCandidate(
                    name=name.strip(), boss_id=data_id, job_intention=job.strip(),
                ))
        logger.info(f"list_chat_index: {len(out)} candidates")
        return out

    async def send_message(self, boss_id: str, text: str) -> bool:
        self._check_daily_limit()
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        try:
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()
            await self._page.wait_for_selector('.chat-conversation', timeout=5000)

            input_el = await self._page.query_selector('#boss-chat-editor-input')
            if not input_el:
                return False
            await input_el.click()
            for ch in text:
                await self._page.keyboard.type(ch, delay=random.randint(50, 150))
                if random.random() < 0.1:
                    await asyncio.sleep(random.uniform(0.3, 0.8))
            await self._random_delay()

            send_btn = await self._page.query_selector('.submit-content .submit')
            if not send_btn:
                return False
            await send_btn.click()
            self._operations_today += 1
            logger.info(f"send_message ok [{boss_id}]")
            return True
        except Exception as e:
            logger.error(f"send_message failed [{boss_id}]: {e}")
            return False

    async def click_request_resume(self, boss_id: str) -> bool:
        self._check_daily_limit()
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        try:
            await self._human_click(f'.geek-item[data-id="{boss_id}"]')
            await self._random_delay()
            await self._page.wait_for_selector('.chat-conversation', timeout=5000)
            for btn in await self._page.query_selector_all('.operate-btn'):
                if '求简历' in (await btn.inner_text()):
                    await btn.click()
                    await self._random_delay()
                    confirm = await self._page.query_selector('.exchange-tooltip .boss-btn-primary')
                    if confirm:
                        await confirm.click()
                    self._operations_today += 1
                    return True
            return False
        except Exception as e:
            logger.error(f"click_request_resume failed [{boss_id}]: {e}")
            return False

    async def list_received_resumes(self) -> list[tuple[str, str]]:
        await self._ensure_browser()
        assert self._page is not None
        await self._random_delay()
        await self._page.goto(self.CHAT_URL, wait_until="networkidle")
        await self._switch_tab("已获取简历")
        await self._random_delay()
        out: list[tuple[str, str]] = []
        for card in await self._page.query_selector_all('.geek-item'):
            data_id = await card.get_attribute("data-id") or ""
            btn = await card.query_selector('.card-btn')
            if not btn:
                continue
            url = await btn.get_attribute("href") or ""
            if data_id and url:
                out.append((data_id, url))
        return out
```

- [ ] **Step 4: Run test**

Run: `pytest tests/adapters/boss/test_playwright_chat_index.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/adapters/boss/base.py app/adapters/boss/playwright_adapter.py tests/adapters/boss/test_playwright_chat_index.py
git commit -m "feat(f4-T8): BossAdapter — list_chat_index/send_message/click_request_resume/list_received_resumes"
```

---

## Task 9: PdfCollector

**Files:**
- Create: `app/modules/im_intake/pdf_collector.py`
- Test: `tests/modules/im_intake/test_pdf_collector.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_pdf_collector.py
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from app.modules.im_intake.pdf_collector import PdfCollector
from app.modules.im_intake.models import IntakeSlot


@pytest.mark.asyncio
async def test_collect_when_pdf_in_received_tab(tmp_path):
    adapter = AsyncMock()
    adapter.list_received_resumes = AsyncMock(return_value=[("bx", "http://x/y.pdf")])
    adapter.download_pdf = AsyncMock(return_value=True)
    slot = IntakeSlot(slot_key="pdf", slot_category="pdf", ask_count=1, asked_at=datetime.now(timezone.utc))

    pc = PdfCollector(adapter=adapter, storage_dir=str(tmp_path))
    pdf_path, status = await pc.try_collect(boss_id="bx", slot=slot)

    assert status == "received"
    assert pdf_path.endswith("bx.pdf")
    adapter.download_pdf.assert_called_once()


@pytest.mark.asyncio
async def test_request_when_first_attempt(tmp_path):
    adapter = AsyncMock()
    adapter.list_received_resumes = AsyncMock(return_value=[])
    adapter.click_request_resume = AsyncMock(return_value=True)
    slot = IntakeSlot(slot_key="pdf", slot_category="pdf", ask_count=0)

    pc = PdfCollector(adapter=adapter, storage_dir=str(tmp_path))
    pdf_path, status = await pc.try_collect(boss_id="bx", slot=slot)

    assert status == "requested"
    assert pdf_path is None
    adapter.click_request_resume.assert_called_once()


@pytest.mark.asyncio
async def test_abandon_after_72h(tmp_path):
    adapter = AsyncMock()
    adapter.list_received_resumes = AsyncMock(return_value=[])
    slot = IntakeSlot(
        slot_key="pdf", slot_category="pdf", ask_count=1,
        asked_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    pc = PdfCollector(adapter=adapter, storage_dir=str(tmp_path), timeout_hours=72)
    pdf_path, status = await pc.try_collect(boss_id="bx", slot=slot)

    assert status == "abandon"
    assert pdf_path is None
    adapter.click_request_resume.assert_not_called()
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_pdf_collector.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement collector**

```python
# app/modules/im_intake/pdf_collector.py
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal, Protocol
from app.modules.im_intake.models import IntakeSlot

logger = logging.getLogger(__name__)

CollectStatus = Literal["received", "requested", "waiting", "abandon", "error"]


class AdapterLike(Protocol):
    async def list_received_resumes(self) -> list[tuple[str, str]]: ...
    async def download_pdf(self, pdf_url: str, save_path: str) -> bool: ...
    async def click_request_resume(self, boss_id: str) -> bool: ...


class PdfCollector:
    def __init__(self, adapter: AdapterLike, storage_dir: str, timeout_hours: int = 72):
        self.adapter = adapter
        self.storage_dir = Path(storage_dir)
        self.timeout_hours = timeout_hours

    async def try_collect(self, boss_id: str, slot: IntakeSlot) -> tuple[str | None, CollectStatus]:
        try:
            received = await self.adapter.list_received_resumes()
        except Exception as e:
            logger.error(f"list_received_resumes failed: {e}")
            return None, "error"

        for bx, url in received:
            if bx == boss_id:
                self.storage_dir.mkdir(parents=True, exist_ok=True)
                save_path = str(self.storage_dir / f"{boss_id}.pdf")
                try:
                    ok = await self.adapter.download_pdf(url, save_path)
                except Exception as e:
                    logger.error(f"download_pdf failed [{boss_id}]: {e}")
                    return None, "error"
                if ok:
                    return save_path, "received"

        if slot.ask_count == 0:
            try:
                ok = await self.adapter.click_request_resume(boss_id)
            except Exception as e:
                logger.error(f"click_request_resume failed: {e}")
                return None, "error"
            return None, "requested" if ok else "error"

        if slot.asked_at is not None:
            asked = slot.asked_at if slot.asked_at.tzinfo else slot.asked_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - asked > timedelta(hours=self.timeout_hours):
                return None, "abandon"

        return None, "waiting"
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_pdf_collector.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/pdf_collector.py tests/modules/im_intake/test_pdf_collector.py
git commit -m "feat(f4-T9): PdfCollector — received/requested/waiting/abandon state machine"
```

---

## Task 10: JobMatcher (fuzzy job-title)

**Files:**
- Create: `app/modules/im_intake/job_matcher.py`
- Test: `tests/modules/im_intake/test_job_matcher.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_job_matcher.py
from app.modules.im_intake.job_matcher import match_job_title

JOBS = [
    {"id": 1, "title": "前端开发工程师"},
    {"id": 2, "title": "Java 后端开发"},
    {"id": 3, "title": "数据分析师"},
]

def test_exact_match():
    assert match_job_title("前端开发工程师", JOBS, threshold=0.7) == 1

def test_fuzzy_match():
    assert match_job_title("前端工程师", JOBS, threshold=0.5) == 1

def test_below_threshold_returns_none():
    assert match_job_title("产品经理", JOBS, threshold=0.7) is None

def test_empty_jobs_returns_none():
    assert match_job_title("前端", [], threshold=0.7) is None
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_job_matcher.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement (reuse F3 string-similarity if present, else inline bigram Jaccard)**

```python
# app/modules/im_intake/job_matcher.py
def _bigrams(s: str) -> set[str]:
    s = s.lower().replace(" ", "")
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def string_similarity(a: str, b: str) -> float:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def match_job_title(boss_job: str, jobs: list[dict], threshold: float = 0.7) -> int | None:
    best_id, best_score = None, 0.0
    for j in jobs:
        s = string_similarity(boss_job, j["title"])
        if s > best_score:
            best_score = s; best_id = j["id"]
    return best_id if best_score >= threshold else None
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_job_matcher.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/job_matcher.py tests/modules/im_intake/test_job_matcher.py
git commit -m "feat(f4-T10): JobMatcher — bigram Jaccard fuzzy match"
```

---

## Task 11: IntakeService.process_one — full pipeline

**Files:**
- Create: `app/modules/im_intake/service.py`
- Test: `tests/modules/im_intake/test_service_pipeline.py`, `test_pending_human.py`, `test_abandoned.py`

- [ ] **Step 1: Write failing happy-path test**

```python
# tests/modules/im_intake/test_service_pipeline.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.adapters.boss.base import BossCandidate, BossMessage
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_first_round_creates_resume_and_sends_hard_questions(db_session, tmp_path):
    job = Job(title="前端开发工程师", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[])
    adapter.send_message = AsyncMock(return_value=True)
    adapter.click_request_resume = AsyncMock(return_value=True)
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), hard_max_asks=3, pdf_timeout_hours=72)
    cand = BossCandidate(name="张三", boss_id="bx1", job_intention="前端开发工程师")

    await svc.process_one(cand)

    r = db_session.query(Resume).filter_by(boss_id="bx1").first()
    assert r is not None
    assert r.intake_status in ("collecting", "awaiting_reply")
    assert r.job_id == job.id
    slots = db_session.query(IntakeSlot).filter_by(resume_id=r.id).all()
    assert {s.slot_key for s in slots} >= {"arrival_date", "free_slots", "intern_duration", "pdf"}
    adapter.send_message.assert_called_once()
    sent_text = adapter.send_message.call_args[0][1]
    assert "张三" in sent_text and "到岗" in sent_text or "入职" in sent_text


@pytest.mark.asyncio
async def test_second_round_parses_reply_and_fills_slots(db_session, tmp_path):
    job = Job(title="前端开发", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()
    r = Resume(name="张三", boss_id="bx1", job_id=job.id, intake_status="awaiting_reply",
               intake_started_at=datetime.now(timezone.utc))
    db_session.add(r); db_session.commit()
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(resume_id=r.id, slot_key=k, slot_category="hard",
                                  ask_count=1, asked_at=datetime.now(timezone.utc)))
    db_session.add(IntakeSlot(resume_id=r.id, slot_key="pdf", slot_category="pdf",
                              ask_count=1, asked_at=datetime.now(timezone.utc)))
    db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[
        BossMessage(sender_id="bx1", sender_name="张三",
                    content="下周一可以到岗，周三下午有空，实习6个月", is_pdf=False),
    ])
    adapter.send_message = AsyncMock(return_value=True)
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), hard_max_asks=3, pdf_timeout_hours=72)
    cand = BossCandidate(name="张三", boss_id="bx1", job_intention="前端开发")

    await svc.process_one(cand)

    db_session.refresh(r)
    arrival = db_session.query(IntakeSlot).filter_by(resume_id=r.id, slot_key="arrival_date").first()
    intern = db_session.query(IntakeSlot).filter_by(resume_id=r.id, slot_key="intern_duration").first()
    assert arrival.value == "下周一" and arrival.source == "regex"
    assert intern.value == "6个月"
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_service_pipeline.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement service**

```python
# app/modules/im_intake/service.py
import logging
from datetime import datetime, timezone
from typing import Protocol
from sqlalchemy.orm import Session
from app.adapters.boss.base import BossAdapter, BossCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.slot_filler import SlotFiller
from app.modules.im_intake.question_generator import QuestionGenerator
from app.modules.im_intake.pdf_collector import PdfCollector
from app.modules.im_intake.job_matcher import match_job_title
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.resume.models import Resume
from app.modules.screening.models import Job

logger = logging.getLogger(__name__)


class IntakeService:
    def __init__(self, db: Session, adapter: BossAdapter, llm,
                 storage_dir: str, hard_max_asks: int = 3, pdf_timeout_hours: int = 72,
                 soft_max_n: int = 3):
        self.db = db
        self.adapter = adapter
        self.llm = llm
        self.filler = SlotFiller(llm=llm)
        self.qg = QuestionGenerator(llm=llm)
        self.pdf = PdfCollector(adapter=adapter, storage_dir=storage_dir, timeout_hours=pdf_timeout_hours)
        self.hard_max_asks = hard_max_asks
        self.soft_max_n = soft_max_n

    async def process_one(self, candidate: BossCandidate) -> None:
        resume, job = self._ensure_resume(candidate)
        if resume is None:
            return
        slots_by_key = self._ensure_slot_rows(resume.id)

        try:
            messages = await self.adapter.get_chat_messages(candidate.boss_id)
        except Exception as e:
            logger.error(f"get_chat_messages failed [{candidate.boss_id}]: {e}")
            return

        candidate_text = "\n".join(m.content for m in messages if m.sender_id == candidate.boss_id)

        pending_hard = [k for k in HARD_SLOT_KEYS if not slots_by_key[k].value]
        if candidate_text and pending_hard:
            parsed = await self.filler.parse_reply(candidate_text, pending_hard)
            for key, (val, source) in parsed.items():
                s = slots_by_key[key]
                s.value = val if isinstance(val, str) else str(val)
                s.source = source
                s.answered_at = datetime.now(timezone.utc)
            self.db.commit()

        pdf_slot = slots_by_key["pdf"]
        if not pdf_slot.value:
            pdf_path, status = await self.pdf.try_collect(candidate.boss_id, pdf_slot)
            if status == "received":
                pdf_slot.value = pdf_path
                pdf_slot.source = "received"
                pdf_slot.answered_at = datetime.now(timezone.utc)
                resume.pdf_path = pdf_path
            elif status == "requested":
                pdf_slot.ask_count += 1
                pdf_slot.asked_at = datetime.now(timezone.utc)
                pdf_slot.last_ask_text = "求简历按钮"
            elif status == "abandon":
                resume.intake_status = "abandoned"
                self.db.commit()
                return
            self.db.commit()

        still_pending_hard = [k for k in HARD_SLOT_KEYS
                              if not slots_by_key[k].value and slots_by_key[k].ask_count < self.hard_max_asks]
        if still_pending_hard:
            packed = self.qg.pack_hard(
                candidate_name=candidate.name,
                job_title=job.title if job else "",
                missing=[(k, slots_by_key[k].ask_count) for k in still_pending_hard],
            )
            ok = await self.adapter.send_message(candidate.boss_id, packed)
            if ok:
                now = datetime.now(timezone.utc)
                for k in still_pending_hard:
                    s = slots_by_key[k]
                    s.ask_count += 1
                    s.asked_at = now
                    s.last_ask_text = packed
                resume.intake_status = "awaiting_reply"
                self.db.commit()

        if pdf_slot.value and resume.raw_text and job and job.competency_model:
            await self._try_send_soft(resume, job, slots_by_key, candidate)

        self._evaluate_completion(resume, slots_by_key)
        self.db.commit()

    def _ensure_resume(self, c: BossCandidate) -> tuple[Resume | None, Job | None]:
        r = self.db.query(Resume).filter_by(boss_id=c.boss_id).first()
        jobs = self.db.query(Job).all()
        job_id = match_job_title(c.job_intention, [{"id": j.id, "title": j.title} for j in jobs], threshold=0.7)
        job = self.db.query(Job).filter_by(id=job_id).first() if job_id else None
        if r is None:
            r = Resume(
                name=c.name, boss_id=c.boss_id, job_id=job_id,
                intake_status="collecting",
                intake_started_at=datetime.now(timezone.utc),
                source="boss_zhipin",
                status="passed",
            )
            self.db.add(r); self.db.commit()
        elif r.job_id is None and job_id:
            r.job_id = job_id
            self.db.commit()
        return r, job

    def _ensure_slot_rows(self, resume_id: int) -> dict[str, IntakeSlot]:
        existing = {s.slot_key: s for s in self.db.query(IntakeSlot).filter_by(resume_id=resume_id).all()}
        for k in HARD_SLOT_KEYS:
            if k not in existing:
                s = IntakeSlot(resume_id=resume_id, slot_key=k, slot_category="hard")
                self.db.add(s); existing[k] = s
        if "pdf" not in existing:
            s = IntakeSlot(resume_id=resume_id, slot_key="pdf", slot_category="pdf")
            self.db.add(s); existing["pdf"] = s
        self.db.commit()
        return existing

    async def _try_send_soft(self, resume: Resume, job: Job, slots: dict, c: BossCandidate) -> None:
        existing_soft = [s for s in slots.values() if s.slot_category == "soft"]
        if existing_soft:
            return
        dims = (job.competency_model or {}).get("assessment_dimensions", [])
        if not dims:
            return
        questions = await self.qg.generate_soft(
            dimensions=[{"id": d.get("name"), "name": d.get("name"), "description": d.get("description", "")}
                        for d in dims],
            resume_summary=resume.raw_text or "",
            max_n=self.soft_max_n,
        )
        if not questions:
            return
        packed = self.qg.pack_soft(questions)
        ok = await self.adapter.send_message(c.boss_id, packed)
        if ok:
            now = datetime.now(timezone.utc)
            for i, q in enumerate(questions):
                s = IntakeSlot(
                    resume_id=resume.id, slot_key=f"soft_q_{i+1}", slot_category="soft",
                    ask_count=1, asked_at=now, last_ask_text=q["question"],
                    question_meta={"dimension_id": q.get("dimension_id"),
                                   "dimension_name": q.get("dimension_name")},
                )
                self.db.add(s); slots[s.slot_key] = s

    def _evaluate_completion(self, r: Resume, slots: dict) -> None:
        hard_filled = all(slots[k].value for k in HARD_SLOT_KEYS)
        hard_exhausted = all(slots[k].value or slots[k].ask_count >= self.hard_max_asks for k in HARD_SLOT_KEYS)
        pdf_done = bool(slots["pdf"].value)

        if hard_filled and pdf_done:
            r.intake_status = "complete"
            r.intake_completed_at = datetime.now(timezone.utc)
        elif hard_exhausted and pdf_done:
            r.intake_status = "pending_human"
            r.intake_completed_at = datetime.now(timezone.utc)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_service_pipeline.py -v`
Expected: PASS (2 tests). Iterate until green.

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/service.py tests/modules/im_intake/test_service_pipeline.py
git commit -m "feat(f4-T11a): IntakeService.process_one — happy path"
```

- [ ] **Step 6: Add pending_human + abandoned tests**

```python
# tests/modules/im_intake/test_pending_human.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from app.adapters.boss.base import BossCandidate
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_pending_human_when_hard_exhausted_pdf_present(db_session, tmp_path):
    job = Job(title="前端", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()
    r = Resume(name="李四", boss_id="bx2", job_id=job.id, intake_status="awaiting_reply",
               intake_started_at=datetime.now(timezone.utc), source="boss_zhipin", status="passed")
    db_session.add(r); db_session.commit()
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(resume_id=r.id, slot_key=k, slot_category="hard",
                                  ask_count=3, asked_at=datetime.now(timezone.utc)))
    pdf_slot = IntakeSlot(resume_id=r.id, slot_key="pdf", slot_category="pdf",
                          value="data/resumes/bx2.pdf", source="received",
                          ask_count=1, answered_at=datetime.now(timezone.utc))
    db_session.add(pdf_slot); db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[])
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), hard_max_asks=3)
    await svc.process_one(BossCandidate(name="李四", boss_id="bx2", job_intention="前端"))

    db_session.refresh(r)
    assert r.intake_status == "pending_human"
```

```python
# tests/modules/im_intake/test_abandoned.py
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from app.adapters.boss.base import BossCandidate
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.models import IntakeSlot
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_abandoned_when_pdf_72h_no_response(db_session, tmp_path):
    job = Job(title="前端", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()
    r = Resume(name="王五", boss_id="bx3", job_id=job.id, intake_status="awaiting_reply",
               intake_started_at=datetime.now(timezone.utc), source="boss_zhipin", status="passed")
    db_session.add(r); db_session.commit()
    db_session.add(IntakeSlot(resume_id=r.id, slot_key="pdf", slot_category="pdf",
                              ask_count=1, asked_at=datetime.now(timezone.utc) - timedelta(hours=73)))
    for k in ("arrival_date", "free_slots", "intern_duration"):
        db_session.add(IntakeSlot(resume_id=r.id, slot_key=k, slot_category="hard"))
    db_session.commit()

    adapter = AsyncMock()
    adapter.get_chat_messages = AsyncMock(return_value=[])
    adapter.list_received_resumes = AsyncMock(return_value=[])

    svc = IntakeService(db=db_session, adapter=adapter, llm=None,
                        storage_dir=str(tmp_path), pdf_timeout_hours=72)
    await svc.process_one(BossCandidate(name="王五", boss_id="bx3", job_intention="前端"))

    db_session.refresh(r)
    assert r.intake_status == "abandoned"
```

Run: `pytest tests/modules/im_intake/test_pending_human.py tests/modules/im_intake/test_abandoned.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add tests/modules/im_intake/test_pending_human.py tests/modules/im_intake/test_abandoned.py
git commit -m "test(f4-T11b): pending_human + abandoned terminal-state tests"
```

---

## Task 12: IntakeScheduler with single-instance lock

**Files:**
- Create: `app/modules/im_intake/scheduler.py`
- Test: `tests/modules/im_intake/test_scheduler_lock.py`
- Modify: `app/config.py` (add F4 settings)

- [ ] **Step 1: Add F4 config**

Edit `app/config.py` (in the Settings class):

```python
    f4_enabled: bool = True
    f4_scan_interval_min: int = 15
    f4_batch_cap: int = 50
    f4_hard_max_asks: int = 3
    f4_pdf_timeout_hours: int = 72
    f4_soft_question_max: int = 3
    ai_model_intake: str = ""
```

- [ ] **Step 2: Write failing test**

```python
# tests/modules/im_intake/test_scheduler_lock.py
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.modules.im_intake.scheduler import IntakeScheduler


@pytest.mark.asyncio
async def test_tick_skips_when_already_locked():
    sched = IntakeScheduler(adapter=AsyncMock(), service_factory=MagicMock(), batch_cap=10)
    await sched._lock.acquire()
    try:
        await sched.tick()
    finally:
        sched._lock.release()
    assert sched.last_batch_size == 0


@pytest.mark.asyncio
async def test_tick_processes_up_to_batch_cap():
    adapter = AsyncMock()
    adapter.list_chat_index = AsyncMock(return_value=[
        MagicMock(boss_id=f"id{i}") for i in range(10)
    ])
    adapter._operations_today = 0
    svc = AsyncMock()
    svc.process_one = AsyncMock()
    factory = MagicMock(return_value=svc)
    sched = IntakeScheduler(adapter=adapter, service_factory=factory, batch_cap=3)
    await sched.tick()
    assert svc.process_one.call_count == 3
    assert sched.last_batch_size == 3


@pytest.mark.asyncio
async def test_pause_resume():
    sched = IntakeScheduler(adapter=AsyncMock(), service_factory=MagicMock(), batch_cap=1)
    sched.pause(); assert not sched.running
    sched.resume(); assert sched.running
```

- [ ] **Step 3: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_scheduler_lock.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement scheduler**

```python
# app/modules/im_intake/scheduler.py
import asyncio
import logging
from datetime import datetime
from typing import Callable
from app.adapters.boss.base import BossAdapter
from app.config import settings

logger = logging.getLogger(__name__)


class IntakeScheduler:
    def __init__(self, adapter: BossAdapter, service_factory: Callable, batch_cap: int = 50):
        self.adapter = adapter
        self.service_factory = service_factory
        self.batch_cap = batch_cap
        self._lock = asyncio.Lock()
        self.running = True
        self.next_run_at: datetime | None = None
        self.last_batch_size: int = 0

    async def tick(self) -> None:
        if not self.running:
            return
        if self._lock.locked():
            logger.info("IntakeScheduler.tick: lock held, skipping")
            self.last_batch_size = 0
            return
        async with self._lock:
            try:
                candidates = await self.adapter.list_chat_index()
            except Exception as e:
                logger.error(f"list_chat_index failed: {e}")
                self.last_batch_size = 0
                return
            cap_remaining = settings.boss_max_operations_per_day - getattr(self.adapter, "_operations_today", 0)
            n = min(len(candidates), self.batch_cap, max(0, cap_remaining))
            self.last_batch_size = n
            for c in candidates[:n]:
                svc = self.service_factory()
                try:
                    await svc.process_one(c)
                except Exception as e:
                    logger.error(f"process_one failed [{c.boss_id}]: {e}")

    def pause(self) -> None:
        self.running = False

    def resume(self) -> None:
        self.running = True

    async def tick_now(self) -> None:
        await self.tick()
```

- [ ] **Step 5: Run test**

Run: `pytest tests/modules/im_intake/test_scheduler_lock.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add app/modules/im_intake/scheduler.py app/config.py tests/modules/im_intake/test_scheduler_lock.py
git commit -m "feat(f4-T12): IntakeScheduler — async lock + batch cap + pause/resume"
```

---

## Task 13: FastAPI router + register in app.main

**Files:**
- Create: `app/modules/im_intake/router.py`
- Modify: `app/main.py`
- Test: `tests/modules/im_intake/test_router.py`

- [ ] **Step 1: Write failing test**

```python
# tests/modules/im_intake/test_router.py
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.modules.resume.models import Resume
from app.modules.im_intake.models import IntakeSlot

client = TestClient(app)


def test_list_candidates_filters_by_status(db_session, auth_headers):
    db_session.add(Resume(name="a", boss_id="ba", intake_status="collecting", source="boss_zhipin", status="passed"))
    db_session.add(Resume(name="b", boss_id="bb", intake_status="complete", source="boss_zhipin", status="passed"))
    db_session.commit()
    r = client.get("/api/intake/candidates?status=collecting", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert any(c["boss_id"] == "ba" for c in body["items"])
    assert all(c["intake_status"] == "collecting" for c in body["items"])


def test_get_candidate_detail_returns_slots(db_session, auth_headers):
    r = Resume(name="c", boss_id="bc", intake_status="collecting", source="boss_zhipin", status="passed")
    db_session.add(r); db_session.commit()
    db_session.add(IntakeSlot(resume_id=r.id, slot_key="arrival_date", slot_category="hard",
                              value="下周一", source="regex", ask_count=1,
                              asked_at=datetime.now(timezone.utc), answered_at=datetime.now(timezone.utc)))
    db_session.commit()
    resp = client.get(f"/api/intake/candidates/{r.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["slot_key"] == "arrival_date" and s["value"] == "下周一" for s in data["slots"])


def test_patch_slot_value(db_session, auth_headers):
    r = Resume(name="d", boss_id="bd", intake_status="pending_human", source="boss_zhipin", status="passed")
    db_session.add(r); db_session.commit()
    s = IntakeSlot(resume_id=r.id, slot_key="intern_duration", slot_category="hard")
    db_session.add(s); db_session.commit()
    resp = client.put(f"/api/intake/slots/{s.id}", json={"value": "6个月"}, headers=auth_headers)
    assert resp.status_code == 200
    db_session.refresh(s)
    assert s.value == "6个月" and s.source == "manual"


def test_scheduler_status(auth_headers):
    r = client.get("/api/intake/scheduler/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "daily_cap_max" in body and "running" in body
```

- [ ] **Step 2: Run + verify failure**

Run: `pytest tests/modules/im_intake/test_router.py -v`
Expected: FAIL — no `/api/intake/...` routes.

- [ ] **Step 3: Implement router**

```python
# app/modules/im_intake/router.py
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.schemas import (
    CandidateOut, CandidateDetailOut, SlotOut, SlotPatchIn, SchedulerStatus,
)
from app.modules.resume.models import Resume
from app.modules.screening.models import Job
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.config import settings

router = APIRouter(prefix="/api/intake", tags=["intake"])


def _scheduler():
    from app.main import intake_scheduler  # late import to avoid circular
    return intake_scheduler


def _candidate_summary(r: Resume, slots: list[IntakeSlot], job_title: str = "") -> CandidateOut:
    expected = list(HARD_SLOT_KEYS) + ["pdf"]
    soft_keys = [s.slot_key for s in slots if s.slot_category == "soft"]
    expected += soft_keys
    done = sum(1 for s in slots if s.value)
    last = max((s.updated_at for s in slots), default=r.intake_started_at)
    return CandidateOut(
        resume_id=r.id, boss_id=r.boss_id, name=r.name,
        job_id=r.job_id, job_title=job_title,
        intake_status=r.intake_status,
        progress_done=done, progress_total=len(expected),
        last_activity_at=last,
    )


@router.get("/candidates")
def list_candidates(
    status: str | None = None,
    job_id: int | None = None,
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(Resume).filter(Resume.boss_id != "")
    if status:
        q = q.filter(Resume.intake_status == status)
    if job_id:
        q = q.filter(Resume.job_id == job_id)
    total = q.count()
    rows = q.order_by(Resume.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    items = []
    for r in rows:
        slots = db.query(IntakeSlot).filter_by(resume_id=r.id).all()
        job = db.query(Job).filter_by(id=r.job_id).first() if r.job_id else None
        items.append(_candidate_summary(r, slots, job.title if job else ""))
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/candidates/{resume_id}", response_model=CandidateDetailOut)
def get_candidate(resume_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(Resume).filter_by(id=resume_id).first()
    if not r:
        raise HTTPException(404, "not found")
    slots = db.query(IntakeSlot).filter_by(resume_id=r.id).all()
    job = db.query(Job).filter_by(id=r.job_id).first() if r.job_id else None
    summary = _candidate_summary(r, slots, job.title if job else "")
    return CandidateDetailOut(
        **summary.model_dump(),
        slots=[SlotOut.model_validate(s, from_attributes=True) for s in slots],
    )


@router.put("/slots/{slot_id}", response_model=SlotOut)
def patch_slot(slot_id: int, body: SlotPatchIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.query(IntakeSlot).filter_by(id=slot_id).first()
    if not s:
        raise HTTPException(404, "slot not found")
    s.value = body.value
    s.source = "manual"
    s.answered_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(s)
    return SlotOut.model_validate(s, from_attributes=True)


@router.post("/candidates/{resume_id}/abandon")
def abandon(resume_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(Resume).filter_by(id=resume_id).first()
    if not r:
        raise HTTPException(404, "not found")
    r.intake_status = "abandoned"
    db.commit(); return {"ok": True}


@router.post("/candidates/{resume_id}/force-complete")
def force_complete(resume_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    r = db.query(Resume).filter_by(id=resume_id).first()
    if not r:
        raise HTTPException(404, "not found")
    r.intake_status = "complete"
    r.intake_completed_at = datetime.now(timezone.utc)
    db.commit(); return {"ok": True}


@router.get("/scheduler/status", response_model=SchedulerStatus)
def scheduler_status(user=Depends(get_current_user)):
    sched = _scheduler()
    used = getattr(sched.adapter, "_operations_today", 0) if sched else 0
    return SchedulerStatus(
        running=sched.running if sched else False,
        next_run_at=sched.next_run_at if sched else None,
        daily_cap_used=used, daily_cap_max=settings.boss_max_operations_per_day,
        last_batch_size=sched.last_batch_size if sched else 0,
    )


@router.post("/scheduler/pause")
def scheduler_pause(user=Depends(get_current_user)):
    sched = _scheduler()
    if sched: sched.pause()
    return {"ok": True}


@router.post("/scheduler/resume")
def scheduler_resume(user=Depends(get_current_user)):
    sched = _scheduler()
    if sched: sched.resume()
    return {"ok": True}


@router.post("/scheduler/tick-now")
async def scheduler_tick(user=Depends(get_current_user)):
    sched = _scheduler()
    if sched: await sched.tick_now()
    return {"ok": True}
```

Edit `app/main.py` — add near the bottom of router includes:

```python
from app.modules.im_intake.router import router as intake_router
app.include_router(intake_router)

intake_scheduler = None  # set during startup
```

In existing FastAPI startup hook (find `@app.on_event("startup")` or `lifespan`), add:

```python
    if settings.f4_enabled:
        from app.modules.im_intake.scheduler import IntakeScheduler
        from app.modules.im_intake.service import IntakeService
        from app.adapters.boss.playwright_adapter import PlaywrightBossAdapter
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.database import SessionLocal
        from app.adapters.ai_provider import get_provider

        adapter = PlaywrightBossAdapter()
        def factory():
            return IntakeService(
                db=SessionLocal(), adapter=adapter,
                llm=get_provider(),
                storage_dir=settings.resume_storage_path,
                hard_max_asks=settings.f4_hard_max_asks,
                pdf_timeout_hours=settings.f4_pdf_timeout_hours,
                soft_max_n=settings.f4_soft_question_max,
            )
        global intake_scheduler
        intake_scheduler = IntakeScheduler(adapter=adapter, service_factory=factory,
                                           batch_cap=settings.f4_batch_cap)
        sched = AsyncIOScheduler()
        sched.add_job(intake_scheduler.tick, "interval",
                      minutes=settings.f4_scan_interval_min, id="f4_intake_tick")
        sched.start()
```

If `app/main.py` does not yet have lifespan/startup, follow the existing pattern in F3 (recruit_bot startup). Verify before editing by reading `app/main.py`.

- [ ] **Step 4: Run test**

Run: `pytest tests/modules/im_intake/test_router.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/modules/im_intake/router.py app/main.py tests/modules/im_intake/test_router.py
git commit -m "feat(f4-T13): intake REST API + APScheduler startup wiring"
```

---

## Task 14: Frontend — Intake.vue + API client + route

**Files:**
- Create: `frontend/src/api/intake.js`, `frontend/src/views/Intake.vue`
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: Implement API client**

```javascript
// frontend/src/api/intake.js
import { request } from './_client'

export const listIntakeCandidates = (params) => request.get('/api/intake/candidates', { params })
export const getIntakeCandidate = (id) => request.get(`/api/intake/candidates/${id}`)
export const patchIntakeSlot = (id, value) => request.put(`/api/intake/slots/${id}`, { value })
export const abandonCandidate = (id) => request.post(`/api/intake/candidates/${id}/abandon`)
export const forceComplete = (id) => request.post(`/api/intake/candidates/${id}/force-complete`)
export const getSchedulerStatus = () => request.get('/api/intake/scheduler/status')
export const pauseScheduler = () => request.post('/api/intake/scheduler/pause')
export const resumeScheduler = () => request.post('/api/intake/scheduler/resume')
export const tickNow = () => request.post('/api/intake/scheduler/tick-now')
```

(If `_client.js` does not exist in this project, copy the import pattern from another existing API module, e.g. `frontend/src/api/jobs.js`.)

- [ ] **Step 2: Implement Intake.vue (single-file component)**

```vue
<!-- frontend/src/views/Intake.vue -->
<template>
  <div class="intake-page">
    <el-card class="control-bar">
      <div class="row">
        <div>
          调度: <el-tag :type="status.running ? 'success' : 'warning'">
            {{ status.running ? '运行中' : '已暂停' }}
          </el-tag>
          | 今日操作: {{ status.daily_cap_used }} / {{ status.daily_cap_max }}
          | 上批次: {{ status.last_batch_size }}
        </div>
        <div>
          <el-button @click="onPauseResume">{{ status.running ? '暂停' : '恢复' }}</el-button>
          <el-button type="primary" @click="onTick">立即扫一次</el-button>
        </div>
      </div>
    </el-card>

    <el-card>
      <div class="row">
        <el-select v-model="filter.status" placeholder="全部状态" clearable @change="reload">
          <el-option v-for="s in statuses" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-input v-model="filter.search" placeholder="姓名 / Boss ID" @change="reload" />
      </div>

      <el-table :data="items" v-loading="loading">
        <el-table-column type="expand">
          <template #default="{ row }">
            <SlotsPanel :resume-id="row.resume_id" @refresh="reload" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="候选人" />
        <el-table-column prop="boss_id" label="Boss ID" />
        <el-table-column prop="job_title" label="岗位" />
        <el-table-column label="状态">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.intake_status)">
              {{ statusLabel(row.intake_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度">
          <template #default="{ row }">
            <el-progress :percentage="Math.round(row.progress_done / row.progress_total * 100)" />
            {{ row.progress_done }} / {{ row.progress_total }}
          </template>
        </el-table-column>
        <el-table-column prop="last_activity_at" label="最近活动" />
      </el-table>

      <el-pagination v-model:current-page="page" :page-size="size" :total="total" @current-change="reload" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import {
  listIntakeCandidates, getSchedulerStatus, pauseScheduler, resumeScheduler, tickNow,
} from '@/api/intake'
import SlotsPanel from './SlotsPanel.vue'

const statuses = [
  { value: 'collecting', label: '收集中' },
  { value: 'awaiting_reply', label: '等回复' },
  { value: 'pending_human', label: '等人工补' },
  { value: 'complete', label: '已入库' },
  { value: 'abandoned', label: '已放弃' },
]
const statusLabel = (s) => statuses.find(x => x.value === s)?.label || s
const statusTagType = (s) => ({
  collecting: 'warning', awaiting_reply: 'info',
  pending_human: 'danger', complete: 'success', abandoned: '',
})[s] || ''

const items = ref([]); const total = ref(0); const page = ref(1); const size = ref(20)
const loading = ref(false)
const filter = ref({ status: '', search: '' })
const status = ref({ running: true, daily_cap_used: 0, daily_cap_max: 1000, last_batch_size: 0 })

let pollTimer = null

async function reload() {
  loading.value = true
  try {
    const res = await listIntakeCandidates({
      status: filter.value.status || undefined,
      page: page.value, size: size.value,
    })
    items.value = res.items; total.value = res.total
  } finally { loading.value = false }
}

async function refreshStatus() { status.value = await getSchedulerStatus() }
async function onPauseResume() {
  status.value.running ? await pauseScheduler() : await resumeScheduler()
  await refreshStatus()
}
async function onTick() { await tickNow(); await reload(); await refreshStatus() }

onMounted(() => {
  reload(); refreshStatus()
  pollTimer = setInterval(refreshStatus, 30_000)
})
onUnmounted(() => clearInterval(pollTimer))
</script>

<style scoped>
.row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.control-bar { margin-bottom: 16px; }
</style>
```

```vue
<!-- frontend/src/views/SlotsPanel.vue -->
<template>
  <div v-loading="loading">
    <h4>硬性必须</h4>
    <el-table :data="hardSlots">
      <el-table-column label="字段" prop="slot_key" />
      <el-table-column label="值">
        <template #default="{ row }">
          <span v-if="row.value">{{ row.value }} <el-tag size="small">{{ row.source }}</el-tag></span>
          <el-input v-else v-model="edits[row.id]" placeholder="人工填入" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="问询次数" prop="ask_count" width="100" />
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button v-if="!row.value && edits[row.id]" size="small" @click="onSave(row)">保存</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h4>PDF 简历</h4>
    <div v-if="pdfSlot">
      <el-tag v-if="pdfSlot.value" type="success">已获取 {{ pdfSlot.value }}</el-tag>
      <el-tag v-else-if="pdfSlot.ask_count > 0" type="warning">已点求简历，等待中</el-tag>
      <el-tag v-else>未触发</el-tag>
    </div>

    <h4>软性问答</h4>
    <el-table :data="softSlots">
      <el-table-column label="维度">
        <template #default="{ row }">{{ row.question_meta?.dimension_name }}</template>
      </el-table-column>
      <el-table-column label="问题" prop="last_ask_text" />
      <el-table-column label="回答" prop="value" />
    </el-table>

    <div style="margin-top: 12px">
      <el-button @click="onAbandon">标记放弃</el-button>
      <el-button type="success" @click="onForce">强制入库</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import {
  getIntakeCandidate, patchIntakeSlot, abandonCandidate, forceComplete,
} from '@/api/intake'

const props = defineProps({ resumeId: { type: Number, required: true } })
const emit = defineEmits(['refresh'])

const detail = ref({ slots: [] })
const loading = ref(false)
const edits = ref({})

const hardSlots = computed(() => detail.value.slots.filter(s => s.slot_category === 'hard'))
const pdfSlot = computed(() => detail.value.slots.find(s => s.slot_category === 'pdf'))
const softSlots = computed(() => detail.value.slots.filter(s => s.slot_category === 'soft'))

async function load() {
  loading.value = true
  try { detail.value = await getIntakeCandidate(props.resumeId) }
  finally { loading.value = false }
}
async function onSave(row) {
  await patchIntakeSlot(row.id, edits.value[row.id]); await load(); emit('refresh')
}
async function onAbandon() { await abandonCandidate(props.resumeId); emit('refresh') }
async function onForce() { await forceComplete(props.resumeId); emit('refresh') }

onMounted(load)
</script>
```

- [ ] **Step 3: Add route**

Edit `frontend/src/router/index.js`:

```javascript
  { path: '/intake', name: 'Intake', component: () => import('@/views/Intake.vue'), meta: { requiresAuth: true } },
```

Add nav link to whichever file holds the side menu (likely `frontend/src/App.vue` or a layout component): `<el-menu-item index="/intake">候选人收集</el-menu-item>`.

- [ ] **Step 4: Build + manual smoke test**

Run:
```bash
cd frontend && pnpm build
cd .. && pnpm test
```
Then start dev server `pnpm dev`, log in, navigate to `/intake`, verify list loads, expand a row, see slot panel.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/intake.js frontend/src/views/Intake.vue frontend/src/views/SlotsPanel.vue frontend/src/router/index.js frontend/src/App.vue
git commit -m "feat(f4-T14): Intake.vue + SlotsPanel.vue + /intake route"
```

---

## Task 15: Integration test — F3 lock priority over F4

**Files:**
- Test: `tests/modules/im_intake/test_concurrent_lock.py`

- [ ] **Step 1: Write test**

```python
# tests/modules/im_intake/test_concurrent_lock.py
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.modules.im_intake.scheduler import IntakeScheduler


@pytest.mark.asyncio
async def test_f4_skips_when_external_holder_uses_adapter():
    adapter = AsyncMock()
    adapter.list_chat_index = AsyncMock(return_value=[MagicMock(boss_id="x")])
    adapter._operations_today = 0
    sched = IntakeScheduler(adapter=adapter, service_factory=MagicMock(), batch_cap=10)

    await sched._lock.acquire()  # simulate F3 holding
    try:
        await sched.tick()
    finally:
        sched._lock.release()
    assert sched.last_batch_size == 0
    adapter.list_chat_index.assert_not_called()
```

- [ ] **Step 2: Run + verify pass**

Run: `pytest tests/modules/im_intake/test_concurrent_lock.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/modules/im_intake/test_concurrent_lock.py
git commit -m "test(f4-T15): scheduler skips when adapter lock held externally"
```

---

## Task 16: End-to-end smoke + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`
- Test: `tests/modules/im_intake/test_e2e_smoke.py`

- [ ] **Step 1: Write smoke test that runs full pipeline against fully-mocked adapter**

```python
# tests/modules/im_intake/test_e2e_smoke.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from app.adapters.boss.base import BossCandidate, BossMessage
from app.main import app
from app.modules.im_intake.scheduler import IntakeScheduler
from app.modules.im_intake.service import IntakeService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_full_intake_to_complete_visible_via_api(db_session, tmp_path, auth_headers):
    job = Job(title="前端", competency_model={"assessment_dimensions": []})
    db_session.add(job); db_session.commit()

    adapter = AsyncMock()
    adapter.list_chat_index = AsyncMock(return_value=[
        BossCandidate(name="赵六", boss_id="bxe", job_intention="前端"),
    ])
    adapter.get_chat_messages = AsyncMock(return_value=[
        BossMessage(sender_id="bxe", sender_name="赵六",
                    content="我下周一可以到岗，周三上午面试，实习6个月", is_pdf=False),
    ])
    adapter.send_message = AsyncMock(return_value=True)
    adapter.click_request_resume = AsyncMock(return_value=True)
    adapter.list_received_resumes = AsyncMock(return_value=[("bxe", "http://x/y.pdf")])
    adapter.download_pdf = AsyncMock(return_value=True)
    adapter._operations_today = 0

    def factory():
        return IntakeService(db=db_session, adapter=adapter, llm=None,
                             storage_dir=str(tmp_path), hard_max_asks=3, pdf_timeout_hours=72)

    sched = IntakeScheduler(adapter=adapter, service_factory=factory, batch_cap=10)
    await sched.tick()

    r = db_session.query(Resume).filter_by(boss_id="bxe").first()
    assert r is not None and r.intake_status == "complete"

    client = TestClient(app)
    resp = client.get("/api/intake/candidates?status=complete", headers=auth_headers)
    assert resp.status_code == 200
    assert any(c["boss_id"] == "bxe" for c in resp.json()["items"])
```

- [ ] **Step 2: Run + verify pass**

Run: `pytest tests/modules/im_intake/test_e2e_smoke.py -v`
Expected: PASS.

- [ ] **Step 3: Add CHANGELOG**

Prepend to `CHANGELOG.md` under the latest section:

```markdown
## [Unreleased]
### Added — F4: Boss IM 候选人信息收集
- 后端 Playwright 守护进程 + APScheduler 15min 定时扫描 chat/index
- `intake_slots` 副表 + `Resume.intake_status` 字段，slot 级 asked/answered 时间戳
- SlotFiller (regex 优先 + LLM 兜底)、QuestionGenerator (硬性模板 + 软性 LLM)、PdfCollector
- IntakeService 完整流水线：硬性 3 次问不到 → pending_human；PDF 72h 不到 → abandoned；齐全 → complete
- REST API `/api/intake/*` + 前端 `Intake.vue` 列表 + slot 详情抽屉
- 与 F3 共享 `BossAdapter` 单例 + asyncio.Lock，F3 优先
- 新增 env: `F4_ENABLED`, `F4_SCAN_INTERVAL_MIN`, `F4_BATCH_CAP`, `F4_HARD_MAX_ASKS`, `F4_PDF_TIMEOUT_HOURS`, `F4_SOFT_QUESTION_MAX`, `AI_MODEL_INTAKE`
```

- [ ] **Step 4: Run full suite + typecheck**

Run:
```bash
pnpm test
pnpm typecheck
```
Expected: ALL GREEN. Fix any regressions.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md tests/modules/im_intake/test_e2e_smoke.py
git commit -m "test(f4-T16): e2e smoke + CHANGELOG entry"
```

---

## Self-Review Notes

Verified against spec §1–§13:
- §2 In-scope items 1–8 → T1–T16 cover each
- §3 Q1–Q9 decisions → encoded in T8/T11/T12 implementations
- §4 architecture → service.process_one structure matches
- §5 schema → T1/T2 produce identical columns/indexes
- §6 module breakdown → T2–T13 file paths match exactly
- §7 API endpoints → all 9 endpoints implemented in T13
- §8 frontend → T14 covers list, slot detail, control bar, manual edit, force/abandon
- §9 config envs → T12 step 1
- §10 testing — TDD enforced; pending_human + abandoned + concurrent lock + e2e smoke all present
- §11 risks — R3 (cap reservation) not implemented as separate task; defer to future iteration if F3/F4 starvation observed (acceptable trade-off, mentioned in spec as `boss_f4_min_cap_ratio`)
- §12 implementation order → T1–T16 follows §12 T1–T12 order with T13–T16 splitting frontend/integration

No placeholders. All steps have concrete code or commands.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-22-f4-boss-im-intake-plan.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
