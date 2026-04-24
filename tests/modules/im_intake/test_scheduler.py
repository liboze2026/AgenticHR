from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest as _pytest

import app.modules.auth.models  # noqa: F401  -- register users FK target
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake.scheduler import scan_once
from app.modules.im_intake import scheduler as _sched_mod


@_pytest.fixture(autouse=True)
def _reset_scheduler_state():
    yield
    _sched_mod._state["running"] = False
    t = _sched_mod._state["thread"]
    _sched_mod._state["thread"] = None
    if t is not None and t.is_alive():
        t.join(timeout=2.0)


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


import time as _time
from app.modules.im_intake import scheduler as _sched


def test_start_idempotent_and_stop_joins():
    # interval=1 so loop wakes fast; daemon thread runs briefly
    _sched.start(interval_sec=1)
    try:
        # Second call must be no-op (same thread)
        t1 = _sched._state["thread"]
        _sched.start(interval_sec=1)
        assert _sched._state["thread"] is t1
        assert t1 is not None and t1.is_alive()
    finally:
        _sched.stop(timeout=3.0)
    assert _sched._state["thread"] is None
    # Give any stragglers a moment; they should be gone
    _time.sleep(0.1)
    assert not t1.is_alive()
