"""E2E concurrency regression: 3 pending outbox rows → 3 sequential claims,
each returns exactly 1. Never 2+ rows in a single response (would re-introduce
the 2026-04-24 char-interleaving bug if the extension had no mutex)."""
from datetime import datetime, timezone

import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
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
        # ack_sent -> record_asked indexes slots by key; create the one referenced below
        db.add(IntakeSlot(candidate_id=c.id, slot_key="arrival_date", slot_category="hard"))
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

    ids = {first[0].id, second[0].id, third[0].id}
    assert len(ids) == 3

    for r in db_session.query(IntakeOutbox).all():
        assert r.status == "claimed"
        assert r.attempts == 1


def test_ack_success_transitions_to_sent_one_at_a_time(db_session, three_pending_running):
    first = claim_batch(db_session, user_id=1)
    ack_sent(db_session, first[0].id)
    assert db_session.query(IntakeOutbox).filter_by(id=first[0].id).first().status == "sent"

    assert db_session.query(IntakeOutbox).filter_by(status="pending").count() == 2
