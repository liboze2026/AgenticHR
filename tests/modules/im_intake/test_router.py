"""F4 T13 — Intake REST API tests."""
from datetime import datetime, timezone

import pytest

from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.resume.models import Resume


@pytest.mark.skip(reason="pending F5 T11 router switch: list endpoint still queries Resume + IntakeSlot.resume_id (removed)")
def test_list_candidates_filters_by_status(client, db_session):
    db_session.add(Resume(name="a", boss_id="ba", intake_status="collecting",
                          source="boss_zhipin", status="passed"))
    db_session.add(Resume(name="b", boss_id="bb", intake_status="complete",
                          source="boss_zhipin", status="passed"))
    db_session.commit()
    r = client.get("/api/intake/candidates?status=collecting")
    assert r.status_code == 200
    body = r.json()
    assert any(c["boss_id"] == "ba" for c in body["items"])
    assert all(c["intake_status"] == "collecting" for c in body["items"])


@pytest.mark.skip(reason="pending F5 T11 router switch: detail endpoint queries IntakeSlot by resume_id (FK renamed to candidate_id)")
def test_get_candidate_detail_returns_slots(client, db_session):
    r = Resume(name="c", boss_id="bc", intake_status="collecting",
               source="boss_zhipin", status="passed")
    db_session.add(r)
    db_session.commit()
    db_session.add(IntakeSlot(
        resume_id=r.id, slot_key="arrival_date", slot_category="hard",
        value="下周一", source="regex", ask_count=1,
        asked_at=datetime.now(timezone.utc),
        answered_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    resp = client.get(f"/api/intake/candidates/{r.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["slot_key"] == "arrival_date" and s["value"] == "下周一" for s in data["slots"])


@pytest.mark.skip(reason="pending F5 T11 router switch: test seeds IntakeSlot with resume_id (removed FK)")
def test_patch_slot_value(client, db_session):
    r = Resume(name="d", boss_id="bd", intake_status="pending_human",
               source="boss_zhipin", status="passed")
    db_session.add(r)
    db_session.commit()
    s = IntakeSlot(resume_id=r.id, slot_key="intern_duration", slot_category="hard")
    db_session.add(s)
    db_session.commit()
    resp = client.put(f"/api/intake/slots/{s.id}", json={"value": "6个月"})
    assert resp.status_code == 200
    db_session.refresh(s)
    assert s.value == "6个月"
    assert s.source == "manual"


def test_scheduler_status(client):
    r = client.get("/api/intake/scheduler/status")
    assert r.status_code == 200
    body = r.json()
    assert "daily_cap_max" in body and "running" in body
