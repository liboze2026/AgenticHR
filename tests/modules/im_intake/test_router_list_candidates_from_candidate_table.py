"""F5 T11 — verify list/detail endpoints source from IntakeCandidate, not Resume."""


def test_list_returns_intake_candidates_not_resumes(client, db_session):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.resume.models import Resume

    db_session.add(IntakeCandidate(boss_id="bxL1", name="列表1", intake_status="collecting", source="plugin"))
    db_session.add(Resume(name="不应出现", boss_id="bxR1", status="passed", source="boss_zhipin", intake_status="complete"))
    db_session.commit()

    r = client.get("/api/intake/candidates")
    assert r.status_code == 200
    names = [it["name"] for it in r.json()["items"]]
    assert "列表1" in names
    assert "不应出现" not in names


def test_detail_returns_candidate_with_slots(client, db_session):
    from app.modules.im_intake.candidate_model import IntakeCandidate
    from app.modules.im_intake.models import IntakeSlot

    c = IntakeCandidate(boss_id="bxD1", name="详情", intake_status="collecting", source="plugin")
    db_session.add(c)
    db_session.commit()
    db_session.add(IntakeSlot(candidate_id=c.id, slot_key="arrival_date", slot_category="hard", value="明天"))
    db_session.commit()

    r = client.get(f"/api/intake/candidates/{c.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "详情"
    assert any(s["slot_key"] == "arrival_date" and s["value"] == "明天" for s in data["slots"])
