from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.models  # noqa: F401  -- register users FK target
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
