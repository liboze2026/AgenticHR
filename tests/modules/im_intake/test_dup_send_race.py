"""Regression: scheduler must not enqueue an outbox row when the extension has
recently analyzed the candidate's chat (path A inline send is in-flight or
just completed). Without this gate, the candidate receives the same question
twice — once via the extension's inline send, once via outbox poll picking
up the scheduler-generated row 30s later.

Also: ack-sent endpoint must expire any leftover pending/claimed outbox rows
for the same candidate so a stale scheduler row from before the inline send
cannot trigger a duplicate.
"""
from datetime import datetime, timezone, timedelta

import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.scheduler import scan_once
from app.modules.im_intake.settings_service import update as settings_update
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _active_candidate(db, *, user_id=1, boss_id="bxR", chat_captured_at=None):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="R",
        intake_status="collecting", source="plugin",
        intake_started_at=now, expires_at=now + timedelta(days=14),
        chat_snapshot={"messages": [],
                       "captured_at": (chat_captured_at or now).isoformat()}
        if chat_captured_at is not None else None,
    )
    db.add(c); db.flush()
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(candidate_id=c.id, slot_key=k, slot_category="hard"))
    db.add(IntakeSlot(candidate_id=c.id, slot_key="pdf", slot_category="pdf"))
    db.commit()
    return c


def test_scheduler_skips_recently_analyzed_candidate(db_session):
    """Candidate's chat_snapshot was captured 30s ago by the extension's
    autoscan. Scheduler should defer — extension is actively driving."""
    db = db_session
    settings_update(db, user_id=1, enabled=True, target_count=99)
    fresh = datetime.now(timezone.utc) - timedelta(seconds=30)
    _active_candidate(db, boss_id="fresh", chat_captured_at=fresh)

    stats = scan_once(db)

    # No outbox rows generated because extension is actively analyzing.
    assert stats["generated"] == 0
    assert db.query(IntakeOutbox).count() == 0


def test_scheduler_emits_for_stale_candidate(db_session):
    """Candidate's chat_snapshot is older than the freshness window —
    extension hasn't covered them. Scheduler is the backstop and emits."""
    db = db_session
    settings_update(db, user_id=1, enabled=True, target_count=99)
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    c = _active_candidate(db, boss_id="stale", chat_captured_at=stale)

    stats = scan_once(db)

    assert stats["generated"] == 1
    rows = db.query(IntakeOutbox).filter_by(candidate_id=c.id).all()
    assert len(rows) == 1


def test_scheduler_emits_when_chat_snapshot_absent(db_session):
    """Brand-new candidate without any chat_snapshot — backend has never
    seen extension push history. Scheduler still emits (existing behavior)."""
    db = db_session
    settings_update(db, user_id=1, enabled=True, target_count=99)
    c = _active_candidate(db, boss_id="brand-new", chat_captured_at=None)

    stats = scan_once(db)

    assert stats["generated"] == 1
    assert db.query(IntakeOutbox).filter_by(candidate_id=c.id).count() == 1


def test_ack_sent_expires_leftover_outbox(client, db_session):
    """After extension's inline send acks, any pre-existing pending outbox
    row for the same candidate (from a prior scheduler tick) must be
    expired so outbox poll cannot dispatch it as a duplicate."""
    c = IntakeCandidate(user_id=1, boss_id="bxLeftover", name="L",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    # Prime slots via collect-chat (creates rows, decision=send_hard).
    r1 = client.post("/api/intake/collect-chat",
                     json={"boss_id": "bxLeftover", "messages": []})
    assert r1.json()["next_action"]["type"] == "send_hard"

    # Simulate scheduler had already enqueued an outbox row for this candidate
    # before the extension's inline send.
    leftover = IntakeOutbox(
        candidate_id=c.id, user_id=1, action_type="send_hard",
        text="Q", slot_keys=["arrival_date"], status="pending",
        scheduled_for=datetime.now(timezone.utc),
    )
    db_session.add(leftover); db_session.commit()
    leftover_id = leftover.id

    # Extension acks its inline send.
    r = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                    json={"action_type": "send_hard", "delivered": True})
    assert r.status_code == 200

    db_session.expire_all()
    row = db_session.query(IntakeOutbox).filter_by(id=leftover_id).first()
    assert row.status == "expired", (
        f"leftover outbox should be expired after inline ack-sent, got {row.status}"
    )


def test_ack_sent_no_outbox_to_expire_is_noop(client, db_session):
    """ack-sent without any pending outbox for the candidate should still
    succeed (no-op cleanup)."""
    c = IntakeCandidate(user_id=1, boss_id="bxNone", name="N",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    client.post("/api/intake/collect-chat",
                json={"boss_id": "bxNone", "messages": []})

    r = client.post(f"/api/intake/candidates/{c.id}/ack-sent",
                    json={"action_type": "send_hard", "delivered": True})
    assert r.status_code == 200
