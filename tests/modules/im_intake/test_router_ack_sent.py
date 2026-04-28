"""F3.1 T10 — POST /api/intake/candidates/{id}/ack-sent tests."""


def test_ack_sent_records_asked(client, db_session):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot

    c = IntakeCandidate(user_id=1, boss_id="bxAck", name="ack测试", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    # Prime slots via collect-chat (creates rows, decides send_hard)
    r1 = client.post("/api/intake/collect-chat", json={"boss_id": "bxAck", "messages": []})
    assert r1.json()["next_action"]["type"] == "send_hard"

    r = client.post(
        f"/api/intake/candidates/{c.id}/ack-sent",
        json={"action_type": "send_hard", "delivered": True},
    )
    assert r.status_code == 200

    slots = {s.slot_key: s for s in db_session.query(IntakeSlot).filter_by(candidate_id=c.id).all()}
    assert slots["arrival_date"].ask_count == 1
    assert slots["arrival_date"].asked_at is not None


def test_ack_state_mismatch_rejects_409(client, db_session):
    """BUG-052: state mismatch on ack-sent rejects 409 instead of silently
    advancing. Outbox is still expired first to prevent duplicate dispatch.
    """
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="bxMis", name="mismatch", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    client.post("/api/intake/collect-chat", json={"boss_id": "bxMis", "messages": []})
    # decision is send_hard, not request_pdf -> state mismatch
    r = client.post(
        f"/api/intake/candidates/{c.id}/ack-sent",
        json={"action_type": "request_pdf", "delivered": True},
    )
    assert r.status_code == 409
    err = r.json()["detail"]
    assert err["error"] == "state_drift"
    assert err["client_action_type"] == "request_pdf"
    assert err["server_action_type"] == "send_hard"


def test_ack_not_delivered_noop(client, db_session):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(user_id=1, boss_id="bxND", name="notd", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.post(
        f"/api/intake/candidates/{c.id}/ack-sent",
        json={"action_type": "send_hard", "delivered": False},
    )
    assert r.status_code == 200
    assert r.json().get("noop") is True
