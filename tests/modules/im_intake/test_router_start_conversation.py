"""F5 T9 — POST /api/intake/candidates/{id}/start-conversation tests."""


def test_start_conversation_returns_deep_link(client, db_session):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    c = IntakeCandidate(boss_id="bxSC1", name="启动测试", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()

    r = client.post(f"/api/intake/candidates/{c.id}/start-conversation")
    assert r.status_code == 200
    data = r.json()
    assert data["candidate_id"] == c.id
    assert data["boss_id"] == "bxSC1"
    assert "zhipin.com" in data["deep_link"]
    assert "bxSC1" in data["deep_link"]
    assert f"intake_candidate_id={c.id}" in data["deep_link"]


def test_start_conversation_404_if_missing(client):
    r = client.post("/api/intake/candidates/99999/start-conversation")
    assert r.status_code == 404
