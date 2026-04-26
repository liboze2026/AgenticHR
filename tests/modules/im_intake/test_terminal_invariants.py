"""Terminal-state invariants for im_intake — defense in depth.

Trigger (2026-04-26 史子杭 incident): an outbox row created 2 days earlier got
claimed and ack-sent AFTER the candidate had already been promoted to a Resume
(terminal state). ``record_asked`` blindly flipped ``intake_status`` back to
``awaiting_reply`` and re-asked the same hard slot. Net result: completed
candidate received the same template question 2 days after collection finished.

These tests pin down the invariants every component must enforce so this
regression cannot recur via ANY path (B-leg orphan, race, manual clicker,
premature ack from extension, scheduler stale tick).

Invariant catalog
-----------------
INV-1  generate_for_candidate refuses terminal candidate
INV-2  claim_batch skips terminal-owned rows AND auto-expires them
INV-3  ack_sent on terminal candidate does NOT downgrade status / re-ask slots
INV-4  reap_stale_claims on terminal candidate → expire (not re-pending)
INV-5  promote_to_resume expires pending/claimed outbox for that candidate
INV-6  apply_terminal(abandon) expires pending/claimed outbox
INV-7  apply_terminal(mark_pending_human) expires pending/claimed outbox
INV-8  record_asked skips already-filled slots (no ask_count regression)
INV-9  record_asked refuses to downgrade terminal candidate to awaiting_reply
INV-10 analyze_chat with messages=[] does NOT clobber existing chat_snapshot
INV-11 analyze_chat that finishes filling all hard slots expires residual outbox
INV-12 cleanup_expired idempotent on already-terminal candidates
"""
from datetime import datetime, timezone, timedelta
import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.im_intake import outbox_service as outbox
from app.modules.im_intake.service import IntakeService
from app.modules.im_intake.promote import promote_to_resume


TERMINAL_STATES = ("complete", "abandoned", "pending_human")


def _mk_terminal(db, *, status="complete", boss_id="bxT", user_id=1):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="T",
        intake_status=status, source="plugin",
        intake_started_at=now - timedelta(hours=2),
        intake_completed_at=now,
        expires_at=now + timedelta(days=14),
    )
    db.add(c); db.commit()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def _mk_active(db, *, boss_id="bxA", user_id=1, status="collecting"):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="A",
        intake_status=status, source="plugin",
        intake_started_at=now,
        expires_at=now + timedelta(days=14),
    )
    db.add(c); db.commit()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


# ---------- INV-1 ----------
@pytest.mark.parametrize("status", TERMINAL_STATES)
def test_generate_refuses_terminal_candidate(db_session, status):
    c = _mk_terminal(db_session, status=status, boss_id=f"bxG_{status}")
    act = NextAction(type="send_hard", text="Q", meta={"slot_keys": ["arrival_date"]})
    row = outbox.generate_for_candidate(db_session, c, act)
    assert row is None, f"must refuse terminal({status})"
    assert db_session.query(IntakeOutbox).filter_by(candidate_id=c.id).count() == 0


# ---------- INV-2 ----------
@pytest.mark.parametrize("status", TERMINAL_STATES)
def test_claim_batch_auto_expires_terminal_orphans(db_session, status):
    c = _mk_active(db_session, boss_id=f"bxC_{status}")
    # Seed pending outbox while still active
    leftover = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="pending",
        scheduled_for=datetime.now(timezone.utc),
    )
    db_session.add(leftover); db_session.commit()
    leftover_id = leftover.id

    # Candidate transitions to terminal AFTER outbox row exists
    c.intake_status = status
    c.intake_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    items = outbox.claim_batch(db_session, user_id=1, limit=1)
    db_session.expire_all()
    row = db_session.query(IntakeOutbox).filter_by(id=leftover_id).first()
    assert row.status == "expired", (
        f"claim_batch must auto-expire orphans of terminal({status}) candidates, got {row.status}"
    )
    assert items == [], "must NOT dispatch terminal-owned rows"


# ---------- INV-3 ----------
@pytest.mark.parametrize("status", TERMINAL_STATES)
def test_ack_sent_does_not_downgrade_terminal(db_session, status):
    c = _mk_active(db_session, boss_id=f"bxK_{status}")
    # Generate while active, claim, then transition to terminal
    act = NextAction(type="send_hard", text="问到岗时间", meta={"slot_keys": ["arrival_date"]})
    row = outbox.generate_for_candidate(db_session, c, act)
    assert row is not None
    items = outbox.claim_batch(db_session, user_id=1, limit=1)
    assert len(items) == 1

    c.intake_status = status
    c.intake_completed_at = datetime.now(timezone.utc)
    db_session.commit()

    # Late ack arrives — must not regress candidate or re-touch slots
    pre_slot = db_session.query(IntakeSlot).filter_by(
        candidate_id=c.id, slot_key="arrival_date").first()
    pre_ask_count = pre_slot.ask_count
    pre_completed = c.intake_completed_at

    outbox.ack_sent(db_session, row.id)
    db_session.expire_all()

    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    s2 = db_session.query(IntakeSlot).filter_by(
        candidate_id=c.id, slot_key="arrival_date").first()
    assert c2.intake_status == status, (
        f"terminal({status}) must NOT regress to awaiting_reply via late ack"
    )
    assert c2.intake_completed_at is not None
    assert s2.ask_count == pre_ask_count, "must NOT increment ask_count for terminal"


# ---------- INV-4 ----------
@pytest.mark.parametrize("status", TERMINAL_STATES)
def test_reap_stale_claims_expires_terminal_orphans(db_session, status):
    c = _mk_active(db_session, boss_id=f"bxR_{status}")
    now = datetime.now(timezone.utc)
    stale = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="claimed",
        claimed_at=now - timedelta(minutes=30),
        scheduled_for=now - timedelta(minutes=30), attempts=1,
    )
    db_session.add(stale); db_session.commit()
    stale_id = stale.id

    c.intake_status = status
    c.intake_completed_at = now
    db_session.commit()

    outbox.reap_stale_claims(db_session, stale_minutes=10, now=now)
    db_session.expire_all()
    row = db_session.query(IntakeOutbox).filter_by(id=stale_id).first()
    assert row.status == "expired", (
        f"reap must expire (not re-pending) orphans of terminal({status}), got {row.status}"
    )


# ---------- INV-5 ----------
def test_promote_to_resume_expires_pending_outbox(db_session):
    c = _mk_active(db_session, boss_id="bxP")
    # All hard slots filled
    now = datetime.now(timezone.utc)
    for k in HARD_SLOT_KEYS:
        s = db_session.query(IntakeSlot).filter_by(candidate_id=c.id, slot_key=k).first()
        s.value = "x"; s.answered_at = now
    db_session.commit()
    # Leftover pending outbox (e.g. scheduler tick from before all slots got filled)
    pending = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="pending",
        scheduled_for=now,
    )
    db_session.add(pending); db_session.commit()
    pending_id = pending.id

    promote_to_resume(db_session, c, user_id=1)
    db_session.commit()
    db_session.expire_all()

    row = db_session.query(IntakeOutbox).filter_by(id=pending_id).first()
    assert row.status == "expired", (
        f"promote must expire pending outbox to prevent zombie sends, got {row.status}"
    )


# ---------- INV-6 ----------
def test_apply_terminal_abandon_expires_pending_outbox(db_session):
    c = _mk_active(db_session, boss_id="bxAb")
    now = datetime.now(timezone.utc)
    pending = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="pending",
        scheduled_for=now,
    )
    db_session.add(pending); db_session.commit()
    pending_id = pending.id

    svc = IntakeService(db=db_session, user_id=1)
    svc.apply_terminal(c, NextAction(type="abandon"), user_id=1)
    db_session.expire_all()

    row = db_session.query(IntakeOutbox).filter_by(id=pending_id).first()
    assert row.status == "expired"
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == "abandoned"


# ---------- INV-7 ----------
def test_apply_terminal_pending_human_expires_pending_outbox(db_session):
    c = _mk_active(db_session, boss_id="bxPh")
    now = datetime.now(timezone.utc)
    claimed = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="claimed",
        claimed_at=now, scheduled_for=now, attempts=1,
    )
    db_session.add(claimed); db_session.commit()
    claimed_id = claimed.id

    svc = IntakeService(db=db_session, user_id=1)
    svc.apply_terminal(c, NextAction(type="mark_pending_human"), user_id=1)
    db_session.expire_all()

    row = db_session.query(IntakeOutbox).filter_by(id=claimed_id).first()
    assert row.status == "expired"
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == "pending_human"


# ---------- INV-8 ----------
def test_record_asked_skips_already_filled_slot(db_session):
    """If the slot was filled between scheduler tick (which scheduled the
    question) and ack_sent (which calls record_asked), do NOT increment
    ask_count for already-filled slots — the question is moot."""
    c = _mk_active(db_session, boss_id="bxF")
    s = db_session.query(IntakeSlot).filter_by(
        candidate_id=c.id, slot_key="arrival_date").first()
    s.value = "下周一"
    s.answered_at = datetime.now(timezone.utc)
    s.ask_count = 0
    db_session.commit()

    svc = IntakeService(db=db_session, user_id=1)
    svc.record_asked(c, NextAction(
        type="send_hard", text="Q", meta={"slot_keys": ["arrival_date"]},
    ))
    db_session.expire_all()
    s2 = db_session.query(IntakeSlot).filter_by(
        candidate_id=c.id, slot_key="arrival_date").first()
    assert s2.ask_count == 0, "filled slot ask_count must NOT regress"


# ---------- INV-9 ----------
@pytest.mark.parametrize("status", TERMINAL_STATES)
def test_record_asked_does_not_downgrade_terminal(db_session, status):
    c = _mk_terminal(db_session, status=status, boss_id=f"bxRD_{status}")
    pre_completed = c.intake_completed_at

    svc = IntakeService(db=db_session, user_id=1)
    svc.record_asked(c, NextAction(
        type="send_hard", text="Q", meta={"slot_keys": ["arrival_date"]},
    ))
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == status, (
        f"terminal({status}) must NOT regress via record_asked"
    )
    assert c2.intake_completed_at is not None


# ---------- INV-10 ----------
@pytest.mark.asyncio
async def test_analyze_chat_empty_messages_preserves_snapshot(db_session):
    c = _mk_active(db_session, boss_id="bxS")
    snap_iso = "2026-04-26T10:00:00+00:00"
    c.chat_snapshot = {"messages": [{"sender_id": "bxS", "content": "hi"}],
                       "captured_at": snap_iso}
    db_session.commit()

    svc = IntakeService(db=db_session, user_id=1, llm=None)
    await svc.analyze_chat(c, messages=[], job=None)
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.chat_snapshot is not None
    assert c2.chat_snapshot.get("messages"), (
        "empty messages must NOT clobber existing snapshot — extension may "
        "be calling collect-chat with no fresh history yet"
    )


# ---------- INV-11 ----------
@pytest.mark.asyncio
async def test_analyze_chat_filled_all_hard_expires_residual_outbox(db_session):
    """Once analyze_chat fills the last unfilled hard slot, any leftover
    pending outbox row (created earlier when slots were unfilled) must be
    expired — sending it would re-ask a question already answered."""
    c = _mk_active(db_session, boss_id="bxFi")
    # Pre-fill two of three hard slots
    now = datetime.now(timezone.utc)
    for k in ("free_slots", "intern_duration"):
        s = db_session.query(IntakeSlot).filter_by(candidate_id=c.id, slot_key=k).first()
        s.value = "x"; s.answered_at = now
    db_session.commit()
    # Pending outbox for last hard slot
    pending = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="pending",
        scheduled_for=now,
    )
    db_session.add(pending); db_session.commit()
    pending_id = pending.id

    # Mock LLM that fills arrival_date
    class _FakeLLM:
        async def parse_conversation(self, messages, boss_id, pending_keys):
            return {"arrival_date": ("下周一", "llm")}
    svc = IntakeService(db=db_session, user_id=1, llm=None)
    svc.filler.parse_conversation = _FakeLLM().parse_conversation

    await svc.analyze_chat(c, messages=[
        {"sender_id": "bxFi", "content": "下周一可以到岗", "sent_at": now.isoformat()},
    ], job=None)
    db_session.expire_all()
    row = db_session.query(IntakeOutbox).filter_by(id=pending_id).first()
    assert row.status == "expired", (
        f"residual outbox must expire after all hard slots filled, got {row.status}"
    )


# ---------- INV-12 ----------
def test_cleanup_expired_idempotent_on_terminal(db_session):
    c = _mk_terminal(db_session, status="abandoned", boss_id="bxIt")
    # Force expires_at into the past
    c.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()

    stats1 = outbox.cleanup_expired(db_session, now=datetime.now(timezone.utc))
    stats2 = outbox.cleanup_expired(db_session, now=datetime.now(timezone.utc))
    # No expires_at-driven abandonment for an already-terminal owner; stale
    # sweep also has nothing to do here (no live outbox rows on this candidate).
    assert stats1["abandoned"] == 0 and stats1["expired_outbox"] == 0
    assert stats2["abandoned"] == 0 and stats2["expired_outbox"] == 0
    assert stats1.get("expired_stale", 0) == 0
    db_session.expire_all()
    c2 = db_session.query(IntakeCandidate).filter_by(id=c.id).first()
    assert c2.intake_status == "abandoned"


# ---------- INV-13 stale-row claim guard ----------
def test_claim_batch_expires_row_older_than_max_age_hours(db_session, monkeypatch):
    """A pending row scheduled more than ``f4_outbox_max_age_hours`` ago
    must NOT be claimed — it auto-expires instead, even when owner is non-terminal.

    Trigger (2026-04-26 王卓恩 incident): scheduler ticked while extension was
    offline for 2 days. When ext came back, 21 stale rows were ready to dispatch
    questions whose conversational context was 32-52h stale.
    """
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "f4_outbox_max_age_hours", 24, raising=False)

    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=1, boss_id="bxStale", name="W",
        intake_status="awaiting_reply", source="plugin",
        intake_started_at=now - timedelta(days=3),
        expires_at=now + timedelta(days=14),
    )
    db_session.add(c); db_session.commit()

    stale = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="?", slot_keys=["arrival_date"], status="pending",
        scheduled_for=now - timedelta(hours=48),
    )
    fresh = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="?", slot_keys=["arrival_date"], status="pending",
        scheduled_for=now - timedelta(minutes=5),
    )
    db_session.add_all([stale, fresh]); db_session.commit()
    stale_id, fresh_id = stale.id, fresh.id

    rows = outbox.claim_batch(db_session, user_id=1, limit=1)
    db_session.expire_all()

    stale_row = db_session.query(IntakeOutbox).filter_by(id=stale_id).first()
    fresh_row = db_session.query(IntakeOutbox).filter_by(id=fresh_id).first()
    assert stale_row.status == "expired", "stale row must auto-expire at claim"
    assert "stale row" in (stale_row.last_error or "")
    # The fresh row should be the one returned (claim_batch picks FIFO but skips stale)
    assert len(rows) == 1
    assert rows[0].id == fresh_id
    assert fresh_row.status == "claimed"


# ---------- INV-14 stale-row cleanup sweep ----------
def test_cleanup_expired_sweeps_stale_rows_regardless_of_owner_state(db_session, monkeypatch):
    """``cleanup_expired`` must sweep all stale pending/claimed rows even when
    owner is non-terminal — defense for the case where ``claim_batch`` is
    blocked (e.g. user paused intake) and stale rows accumulate."""
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "f4_outbox_max_age_hours", 24, raising=False)

    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=1, boss_id="bxSweep", name="X",
        intake_status="awaiting_reply", source="plugin",
        intake_started_at=now - timedelta(days=3),
        expires_at=now + timedelta(days=14),
    )
    db_session.add(c); db_session.commit()

    stale_pending = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="?", slot_keys=[], status="pending",
        scheduled_for=now - timedelta(hours=72),
    )
    stale_claimed = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="?", slot_keys=[], status="claimed",
        scheduled_for=now - timedelta(hours=72),
        claimed_at=now - timedelta(hours=70),
    )
    fresh = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="?", slot_keys=[], status="pending",
        scheduled_for=now - timedelta(minutes=10),
    )
    db_session.add_all([stale_pending, stale_claimed, fresh]); db_session.commit()
    sp, sc, fr = stale_pending.id, stale_claimed.id, fresh.id

    stats = outbox.cleanup_expired(db_session, now=now)
    assert stats["expired_stale"] == 2
    db_session.expire_all()
    assert db_session.query(IntakeOutbox).filter_by(id=sp).first().status == "expired"
    assert db_session.query(IntakeOutbox).filter_by(id=sc).first().status == "expired"
    assert db_session.query(IntakeOutbox).filter_by(id=fr).first().status == "pending"


# ---------- INV-15 stale + terminal precedence ----------
def test_claim_batch_stale_row_on_terminal_owner_still_expires(db_session, monkeypatch):
    """Both 'stale' and 'terminal owner' independently expire the row; verify a
    row that is both stale AND terminal-owned still ends up expired (no double-flip)."""
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "f4_outbox_max_age_hours", 24, raising=False)

    now = datetime.now(timezone.utc)
    c = _mk_terminal(db_session, status="complete", boss_id="bxStaleTerm")
    row = IntakeOutbox(
        candidate_id=c.id, user_id=c.user_id, action_type="send_hard",
        text="?", slot_keys=[], status="pending",
        scheduled_for=now - timedelta(hours=48),
    )
    db_session.add(row); db_session.commit()
    rid = row.id

    rows = outbox.claim_batch(db_session, user_id=c.user_id, limit=1)
    db_session.expire_all()
    assert rows == []
    flushed = db_session.query(IntakeOutbox).filter_by(id=rid).first()
    assert flushed.status == "expired"
    # Stale check runs first, so error tag is the stale one (deterministic order)
    assert "stale row" in (flushed.last_error or "")
