"""HTTP API for /api/intake/settings."""


def test_get_settings_creates_defaults(client):
    r = client.get("/api/intake/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["target_count"] == 0
    assert body["complete_count"] == 0
    assert body["is_running"] is False


def test_put_settings_updates_fields(client):
    r = client.put("/api/intake/settings",
                   json={"enabled": True, "target_count": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["target_count"] == 50


def test_put_settings_rejects_negative_target(client):
    r = client.put("/api/intake/settings",
                   json={"target_count": -1})
    assert r.status_code == 422


def test_put_settings_partial_keeps_other_field(client):
    client.put("/api/intake/settings", json={"target_count": 30, "enabled": True})
    r = client.put("/api/intake/settings", json={"enabled": False})
    body = r.json()
    assert body["enabled"] is False
    assert body["target_count"] == 30


# ---- F5 Task 8: /autoscan/rank and /outbox/claim gated on is_running ----

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.outbox_model import IntakeOutbox
from datetime import datetime, timezone

_UID = 1  # client fixture authenticates as user_id=1


def test_autoscan_rank_returns_empty_when_paused(client, db_session):
    db_session.add(IntakeCandidate(user_id=_UID, boss_id="z1",
                                   intake_status="collecting", source="plugin"))
    db_session.commit()
    client.put("/api/intake/settings", json={"enabled": False, "target_count": 10})
    r = client.get("/api/intake/autoscan/rank")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_autoscan_rank_returns_items_when_running(client, db_session):
    db_session.add(IntakeCandidate(user_id=_UID, boss_id="z2",
                                   intake_status="collecting", source="plugin"))
    db_session.commit()
    client.put("/api/intake/settings", json={"enabled": True, "target_count": 10})
    r = client.get("/api/intake/autoscan/rank")
    assert len(r.json()["items"]) == 1


def test_outbox_claim_returns_empty_when_paused(client, db_session):
    c = IntakeCandidate(user_id=_UID, boss_id="z3",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.flush()
    db_session.add(IntakeOutbox(candidate_id=c.id, user_id=_UID,
                                action_type="send_hard", text="hi",
                                slot_keys=[], status="pending",
                                scheduled_for=datetime.now(timezone.utc)))
    db_session.commit()
    client.put("/api/intake/settings", json={"enabled": False, "target_count": 10})
    r = client.post("/api/intake/outbox/claim", json={"limit": 1})
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_outbox_claim_returns_items_when_running(client, db_session):
    c = IntakeCandidate(user_id=_UID, boss_id="z4",
                        intake_status="collecting", source="plugin")
    db_session.add(c); db_session.flush()
    db_session.add(IntakeOutbox(candidate_id=c.id, user_id=_UID,
                                action_type="send_hard", text="hi",
                                slot_keys=[], status="pending",
                                scheduled_for=datetime.now(timezone.utc)))
    db_session.commit()
    client.put("/api/intake/settings", json={"enabled": True, "target_count": 10})
    r = client.post("/api/intake/outbox/claim", json={"limit": 1})
    assert len(r.json()["items"]) == 1
