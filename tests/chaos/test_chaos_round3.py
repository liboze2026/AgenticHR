"""Chaos round 3 regression — bugs fixed in BUG-056..086. Tests assert NEW behavior."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.resume.models import Resume


def _seed_complete_candidate(session, *, user_id, boss_id, name="C",
                             promote=True):
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        phone="13800000000", email="x@x.com",
        pdf_path="data/x.pdf", intake_status="complete",
        skills="Python", education="本科",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    for k in HARD_SLOT_KEYS:
        session.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="filled", ask_count=1,
        ))
    if promote:
        r = Resume(user_id=user_id, name=name, boss_id=boss_id,
                   phone="13800000000", source="boss_zhipin",
                   pdf_path="data/x.pdf", status="passed")
        session.add(r)
        session.commit()
        c.promoted_resume_id = r.id
    session.commit()
    return c


# BUG-056 fixed: cross-user resource and missing both return 404
def test_BUG_056_cross_user_returns_404_not_403(client, db_session):
    other = _seed_complete_candidate(db_session, user_id=2, boss_id="b_other")
    resp_other = client.get(f"/api/resumes/{other.id}")
    resp_unknown = client.get("/api/resumes/9999999")
    assert resp_other.status_code == 404
    assert resp_unknown.status_code == 404


# BUG-057 fixed: status update on candidate without promoted_resume auto-promotes
def test_BUG_057_status_update_auto_promotes_if_needed(client, db_session):
    c = _seed_complete_candidate(db_session, user_id=1,
                                 boss_id="b_no_prom", promote=False)
    assert c.promoted_resume_id is None
    resp = client.patch(f"/api/resumes/{c.id}", json={"status": "rejected"})
    assert resp.status_code == 200
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.promoted_resume_id is not None  # auto-promoted
    r = db_session.query(Resume).get(cand.promoted_resume_id)
    assert r.status == "rejected"  # status persisted


# BUG-058 fixed: cross-user write via corrupted FK is rejected
def test_BUG_058_patch_does_not_write_other_users_resume(client, db_session):
    other_resume = Resume(user_id=2, name="他人简历", source="manual")
    db_session.add(other_resume)
    db_session.commit()

    c = _seed_complete_candidate(db_session, user_id=1,
                                 boss_id="b_corrupt", promote=False)
    c.promoted_resume_id = other_resume.id  # FK corruption
    db_session.commit()

    resp = client.patch(f"/api/resumes/{c.id}", json={"name": "试图改"})
    assert resp.status_code == 200

    db_session.expire_all()
    pwned = db_session.query(Resume).get(other_resume.id)
    assert pwned.name == "他人简历"  # unchanged
    assert pwned.user_id == 2


# BUG-060 fixed: dict seniority no longer crashes
def test_BUG_060_dict_seniority_no_crash():
    from app.modules.resume.router import _apply_parsed_fields
    target = Resume(name="T", phone="", email="", job_intention="")
    _apply_parsed_fields(target, {"seniority": {"level": "高级"}})
    # _s() converts dict to str; .strip() succeeds on the str
    assert "高级" in target.seniority


# BUG-067 fixed: status enum validated
def test_BUG_067_arbitrary_status_rejected():
    from app.modules.resume.schemas import ResumeUpdate
    with pytest.raises(Exception):
        ResumeUpdate(status="completely_invalid_status_xyz")


# BUG-069 fixed: empty name rejected
def test_BUG_069_empty_name_rejected():
    from app.modules.resume.schemas import ResumeUpdate
    with pytest.raises(Exception):
        ResumeUpdate(name="")


# BUG-070 fixed: expected_salary_min accepted in schema
def test_BUG_070_expected_salary_now_accepted(client, db_session):
    from app.modules.resume.schemas import ResumeUpdate
    u = ResumeUpdate(expected_salary_min=30000)
    assert u.expected_salary_min == 30000

    c = _seed_complete_candidate(db_session, user_id=1,
                                 boss_id="b_salary", promote=True)
    resp = client.patch(f"/api/resumes/{c.id}",
                        json={"expected_salary_min": 30000})
    assert resp.status_code == 200
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.expected_salary_min == 30000


# BUG-068 fixed: abandoned candidate shows status=rejected
def test_BUG_068_abandoned_candidate_status_mapped():
    from app.modules.resume.intake_view_service import candidate_to_resume_dict
    c = IntakeCandidate(
        id=999, user_id=1, boss_id="b_aban",
        name="A", intake_status="abandoned",
        pdf_path="data/x.pdf",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    d = candidate_to_resume_dict(c)
    assert d["status"] == "rejected"
    assert d["intake_status"] == "abandoned"


# BUG-079 fixed: completed interview does not block new interview
def test_BUG_079_completed_does_not_block_new(client, db_session):
    from app.modules.scheduling.models import Interview, Interviewer

    c = _seed_complete_candidate(db_session, user_id=1,
                                 boss_id="b_iv", promote=True)
    iv = Interviewer(user_id=1, name="面试官", phone="13900000099",
                     email="iv@x.com")
    db_session.add(iv)
    db_session.commit()

    db_session.add(Interview(
        resume_id=c.promoted_resume_id, interviewer_id=iv.id,
        start_time=datetime.now(timezone.utc) - timedelta(days=2),
        end_time=datetime.now(timezone.utc) - timedelta(days=2, hours=-1),
        status="completed",
    ))
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    resp = client.post("/api/scheduling/interviews", json={
        "resume_id": c.id,
        "interviewer_id": iv.id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    })
    assert resp.status_code == 201
    body = resp.json()
    # InterviewResponse now exposes resume_name + candidate_id (BUG-076)
    assert body["resume_name"] == "C"
    assert body["candidate_id"] == c.id


# BUG-076 regression: InterviewResponse exposes resume_name and candidate_id
def test_BUG_076_interview_response_has_resume_name(client, db_session):
    from app.modules.scheduling.models import Interviewer

    c = _seed_complete_candidate(db_session, user_id=1,
                                 boss_id="b_iv2", name="张三", promote=True)
    iv = Interviewer(user_id=1, name="李面试官", phone="13900000077",
                     email="iv2@x.com")
    db_session.add(iv)
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    resp = client.post("/api/scheduling/interviews", json={
        "resume_id": c.id,
        "interviewer_id": iv.id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["resume_name"] == "张三"
    assert body["interviewer_name"] == "李面试官"
    assert body["candidate_id"] == c.id


# BUG-082 fixed: keyword length capped
def test_BUG_082_keyword_length_capped(client):
    long_kw = "a" * 100
    resp = client.get(f"/api/resumes/?keyword={long_kw}")
    assert resp.status_code == 422


# BUG-085 fixed: ai-parse with no input returns 400 not 500
def test_BUG_085_ai_parse_no_input_returns_400(client, db_session, monkeypatch):
    c = _seed_complete_candidate(db_session, user_id=1,
                                 boss_id="b_no_input", promote=True)
    c.pdf_path = ""  # no PDF
    c.raw_text = ""  # no text
    db_session.commit()
    r = db_session.query(Resume).get(c.promoted_resume_id)
    r.pdf_path = ""
    r.raw_text = ""
    db_session.commit()

    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "ai_enabled", True, raising=False)
    with patch("app.adapters.ai_provider.AIProvider.is_configured",
               lambda self: True):
        resp = client.post(f"/api/resumes/{c.id}/ai-parse")
    assert resp.status_code == 400
    assert "没有 PDF" in resp.json()["detail"]
