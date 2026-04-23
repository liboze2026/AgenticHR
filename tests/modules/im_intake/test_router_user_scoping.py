"""F3.1 multi-tenancy: IntakeCandidate list/detail must filter by user_id."""
from app.modules.im_intake.candidate_model import IntakeCandidate


def test_list_only_shows_current_users_candidates(client, db_session):
    # client fixture pins user_id=1; seed one row owned by a different user
    db_session.add(IntakeCandidate(user_id=2, boss_id="bxOther", name="他人", intake_status="collecting", source="plugin"))
    db_session.add(IntakeCandidate(user_id=1, boss_id="bxMine", name="我的", intake_status="collecting", source="plugin"))
    db_session.commit()

    r = client.get("/api/intake/candidates")
    assert r.status_code == 200
    names = [it["name"] for it in r.json()["items"]]
    assert "我的" in names
    assert "他人" not in names


def test_detail_returns_404_for_other_users_candidate(client, db_session):
    c = IntakeCandidate(user_id=2, boss_id="bxOther2", name="别人", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.get(f"/api/intake/candidates/{c.id}")
    assert r.status_code == 404


def test_abandon_returns_404_for_other_users_candidate(client, db_session):
    c = IntakeCandidate(user_id=2, boss_id="bxOther3", name="X", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.post(f"/api/intake/candidates/{c.id}/abandon")
    assert r.status_code == 404


def test_start_conversation_returns_404_for_other_users_candidate(client, db_session):
    c = IntakeCandidate(user_id=2, boss_id="bxOther4", name="Y", intake_status="collecting", source="plugin")
    db_session.add(c); db_session.commit()
    r = client.post(f"/api/intake/candidates/{c.id}/start-conversation")
    assert r.status_code == 404
