"""Regression: ack-sent must expire any leftover pending/claimed outbox rows
for the same candidate so a stale row cannot trigger a duplicate send."""
from datetime import datetime, timezone

import pytest

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox


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
