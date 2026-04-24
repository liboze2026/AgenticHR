from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.models  # noqa: F401  -- register users FK target
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.outbox_service import generate_for_candidate, claim_batch, ack_sent, ack_failed


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


def test_claim_batch_transitions_pending_to_claimed():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    generate_for_candidate(db, c, act)

    items = claim_batch(db, user_id=1, limit=5)
    assert len(items) == 1
    assert items[0].status == "claimed"
    assert items[0].claimed_at is not None
    assert items[0].attempts == 1


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
    texts = [x.text for x in items]
    assert texts == ["Q0", "Q1", "Q2"]


def test_claim_batch_skips_already_claimed():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    row = generate_for_candidate(db, c, act)
    row.status = "claimed"; db.commit()
    assert claim_batch(db, user_id=1, limit=10) == []


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
    # 失败后回 pending 以便下次再试（attempts 已在 claim 时 +1）
    assert row.status == "pending"
    assert row.last_error == "tab closed"
    assert c.intake_status == "collecting"  # not advanced
