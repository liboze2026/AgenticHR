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
