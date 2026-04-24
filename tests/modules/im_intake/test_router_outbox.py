"""F4 outbox HTTP API — claim + ack endpoints."""
from datetime import datetime, timezone, timedelta

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.outbox_model import IntakeOutbox
from app.modules.im_intake.decision import NextAction
from app.modules.im_intake.outbox_service import generate_for_candidate


def _mk(db, uid=1, boss_id="bxR"):
    now = datetime.now(timezone.utc)
    c = IntakeCandidate(user_id=uid, boss_id=boss_id, name="R",
                        intake_status="collecting", source="plugin",
                        intake_started_at=now, expires_at=now + timedelta(days=14))
    db.add(c); db.commit()
    db.add(IntakeSlot(candidate_id=c.id, slot_key="phone", slot_category="hard"))
    db.commit()
    return c


def test_outbox_claim_returns_pending_items_and_marks_claimed(client, db_session):
    c = _mk(db_session)
    generate_for_candidate(db_session, c, NextAction(type="send_hard", text="Q",
                                                     meta={"slot_keys": ["phone"]}))

    r = client.post("/api/intake/outbox/claim", json={"limit": 5})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["action_type"] == "send_hard"
    assert items[0]["text"] == "Q"
    assert items[0]["slot_keys"] == ["phone"]
    assert items[0]["boss_id"] == "bxR"

    r2 = client.post("/api/intake/outbox/claim", json={"limit": 5})
    assert r2.json()["items"] == []


def test_outbox_ack_success_transitions_candidate_and_slot(client, db_session):
    c = _mk(db_session, boss_id="bxAckOK")
    row = generate_for_candidate(db_session, c, NextAction(type="send_hard", text="Q",
                                                           meta={"slot_keys": ["phone"]}))
    row.status = "claimed"
    db_session.commit()
    row_id = row.id
    cand_id = c.id

    r = client.post(f"/api/intake/outbox/{row_id}/ack", json={"success": True})
    assert r.status_code == 200

    db_session.expire_all()
    row = db_session.query(IntakeOutbox).filter_by(id=row_id).first()
    cand = db_session.query(IntakeCandidate).filter_by(id=cand_id).first()
    slot = db_session.query(IntakeSlot).filter_by(candidate_id=cand_id, slot_key="phone").first()
    assert row.status == "sent"
    assert cand.intake_status == "awaiting_reply"
    assert slot.ask_count == 1


def test_outbox_ack_failure_requeues(client, db_session):
    c = _mk(db_session, boss_id="bxAckFail")
    row = generate_for_candidate(db_session, c, NextAction(type="send_hard", text="Q",
                                                           meta={"slot_keys": ["phone"]}))
    row.status = "claimed"
    db_session.commit()
    row_id = row.id

    r = client.post(f"/api/intake/outbox/{row_id}/ack",
                    json={"success": False, "error": "tab closed"})
    assert r.status_code == 200

    db_session.expire_all()
    row = db_session.query(IntakeOutbox).filter_by(id=row_id).first()
    assert row.status == "pending"
    assert row.last_error == "tab closed"


def test_outbox_ack_404_for_other_users_row(client, db_session):
    # Row belongs to user 2; client is user 1 → 404
    c = _mk(db_session, uid=2, boss_id="bxOther")
    row = generate_for_candidate(db_session, c, NextAction(type="send_hard", text="Q",
                                                           meta={"slot_keys": ["phone"]}))
    row_id = row.id

    r = client.post(f"/api/intake/outbox/{row_id}/ack", json={"success": True})
    assert r.status_code == 404
