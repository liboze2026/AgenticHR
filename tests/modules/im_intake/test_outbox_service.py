from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.modules.auth.models  # noqa: F401  -- register users FK target
from app.database import Base
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.outbox_service import (
    generate_for_candidate, claim_batch, ack_sent, ack_failed, cleanup_expired,
    reap_stale_claims,
)


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

    items = claim_batch(db, user_id=1, limit=1)
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

    u1_items = claim_batch(db, user_id=1, limit=1)
    assert len(u1_items) == 1
    assert u1_items[0].candidate_id == c1.id


def test_claim_batch_respects_limit_and_fifo():
    # After the 2026-04-24 hard-cap, claim_batch always returns exactly 1 row
    # regardless of the requested limit. FIFO order is preserved: the earliest
    # scheduled row is returned.
    db = _make_session()
    for i in range(5):
        c = _mk_candidate(db, boss_id=f"bx{i}")
        act = NextAction(type="send_hard", text=f"Q{i}", meta={"slot_keys": ["phone"]})
        generate_for_candidate(db, c, act)
    items = claim_batch(db, user_id=1, limit=3)  # proves hard-clamp: wide limit still returns 1
    assert len(items) == 1
    assert items[0].text == "Q0"  # earliest (FIFO) row returned


def test_claim_batch_skips_already_claimed():
    db = _make_session()
    c = _mk_candidate(db)
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["phone"]})
    row = generate_for_candidate(db, c, act)
    row.status = "claimed"; db.commit()
    assert claim_batch(db, user_id=1, limit=1) == []


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


def test_cleanup_expired_skips_null_expires_at():
    db = _make_session()
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=1, boss_id="bxNull", name="N",
                        intake_status="collecting", source="plugin",
                        intake_started_at=now, expires_at=None)
    db.add(c); db.commit()

    stats = cleanup_expired(db, now=now)
    db.refresh(c)
    assert c.intake_status == "collecting"
    assert stats["abandoned"] == 0
    assert stats["expired_outbox"] == 0


def test_cleanup_expired_handles_awaiting_reply():
    db = _make_session()
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=1, boss_id="bxAwait", name="W",
                        intake_status="awaiting_reply", source="plugin",
                        intake_started_at=now - timedelta(days=20),
                        expires_at=now - timedelta(days=1))
    db.add(c); db.commit()

    stats = cleanup_expired(db, now=now)
    db.refresh(c)
    assert c.intake_status == "abandoned"
    assert stats["abandoned"] == 1


def test_cleanup_expired_skips_already_terminal():
    db = _make_session()
    now = datetime.now(timezone.utc)
    done = IntakeCandidate(user_id=1, boss_id="bxDone", name="D",
                           intake_status="abandoned", source="plugin",
                           intake_started_at=now - timedelta(days=20),
                           expires_at=now - timedelta(days=1))
    complete = IntakeCandidate(user_id=1, boss_id="bxComp", name="C",
                               intake_status="complete", source="plugin",
                               intake_started_at=now - timedelta(days=20),
                               expires_at=now - timedelta(days=1))
    db.add_all([done, complete]); db.commit()
    # Seed outbox rows directly (bypass generate_for_candidate's status filter)
    ob_done = IntakeOutbox(candidate_id=done.id, user_id=1, action_type="send_hard",
                           text="Q", slot_keys=["phone"], status="pending",
                           scheduled_for=now)
    ob_comp = IntakeOutbox(candidate_id=complete.id, user_id=1, action_type="send_hard",
                           text="Q", slot_keys=["phone"], status="pending",
                           scheduled_for=now)
    db.add_all([ob_done, ob_comp]); db.commit()

    stats = cleanup_expired(db, now=now)
    db.refresh(done); db.refresh(complete); db.refresh(ob_done); db.refresh(ob_comp)
    assert done.intake_status == "abandoned"
    assert complete.intake_status == "complete"
    assert ob_done.status == "pending"
    assert ob_comp.status == "pending"
    assert stats["abandoned"] == 0
    assert stats["expired_outbox"] == 0


def test_cleanup_expired_empty_returns_zero():
    db = _make_session()
    stats = cleanup_expired(db, now=datetime.now(timezone.utc))
    assert stats["abandoned"] == 0
    assert stats["expired_outbox"] == 0


def test_cleanup_expired_does_not_touch_sent_or_failed_outbox():
    db = _make_session()
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=1, boss_id="bxMix", name="M",
                        intake_status="collecting", source="plugin",
                        intake_started_at=now - timedelta(days=20),
                        expires_at=now - timedelta(days=1))
    db.add(c); db.commit()
    pending = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                           text="Q1", slot_keys=["phone"], status="pending",
                           scheduled_for=now)
    sent = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                        text="Q2", slot_keys=["phone"], status="sent",
                        scheduled_for=now, sent_at=now)
    db.add_all([pending, sent]); db.commit()

    stats = cleanup_expired(db, now=now)
    db.refresh(c); db.refresh(pending); db.refresh(sent)
    assert c.intake_status == "abandoned"
    assert pending.status == "expired"
    assert sent.status == "sent"
    assert stats["abandoned"] == 1
    assert stats["expired_outbox"] == 1


def test_reap_stale_claims_reverts_old_claimed_to_pending():
    db = _make_session()
    c = _mk_candidate(db)
    now = datetime.now(timezone.utc)
    old = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                       text="Q", slot_keys=["x"], status="claimed",
                       claimed_at=now - timedelta(minutes=15),
                       scheduled_for=now - timedelta(minutes=15), attempts=1)
    fresh = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                         text="Q2", slot_keys=["y"], status="claimed",
                         claimed_at=now - timedelta(minutes=2),
                         scheduled_for=now - timedelta(minutes=2), attempts=1)
    db.add_all([old, fresh]); db.commit()

    reaped = reap_stale_claims(db, stale_minutes=10, now=now)
    db.refresh(old); db.refresh(fresh)
    assert reaped == 1
    assert old.status == "pending"
    assert old.claimed_at is None
    assert old.attempts == 1  # do not re-increment; counts at claim-time only
    assert fresh.status == "claimed"


def test_reap_stale_claims_ignores_non_claimed_states():
    db = _make_session()
    c = _mk_candidate(db)
    now = datetime.now(timezone.utc)
    for st in ("pending", "sent", "expired"):
        db.add(IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                            text="Q", slot_keys=[], status=st,
                            claimed_at=now - timedelta(hours=1),
                            scheduled_for=now - timedelta(hours=1)))
    db.commit()
    reaped = reap_stale_claims(db, stale_minutes=10, now=now)
    assert reaped == 0


def test_reap_stale_claims_tz_naive_defensive():
    """Some DBs (SQLite) strip tzinfo on roundtrip. Reaper must still compare correctly."""
    db = _make_session()
    c = _mk_candidate(db)
    now = datetime.now(timezone.utc)
    row = IntakeOutbox(candidate_id=c.id, user_id=1, action_type="send_hard",
                       text="Q", slot_keys=[], status="claimed",
                       claimed_at=(now - timedelta(minutes=30)).replace(tzinfo=None),
                       scheduled_for=now - timedelta(minutes=30), attempts=1)
    db.add(row); db.commit()
    reaped = reap_stale_claims(db, stale_minutes=10, now=now)
    db.refresh(row)
    assert reaped == 1
    assert row.status == "pending"
