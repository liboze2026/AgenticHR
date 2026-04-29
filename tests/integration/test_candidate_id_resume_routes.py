"""E2E 回归：迁移 0020/0021 后 GET /api/resumes/ 返回 IntakeCandidate.id 作为行键，
所有以 resume_id 为入参的端点必须接受 candidate.id（含自动 promote 到 Resume）。

覆盖：
- /api/resumes/{candidate.id} GET / PATCH / DELETE / ai-parse
- /api/matching/score / results / recompute (resume_id=candidate.id)
- /api/scheduling/interviews POST (resume_id=candidate.id)
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS
from app.modules.resume.models import Resume
from app.modules.screening.models import Job
from app.modules.scheduling.models import Interviewer, Interview
from app.modules.matching.models import MatchingResult


def _seed_candidate(session, *, user_id=1, boss_id="b_e2e",
                    name="测试候选", with_promoted_resume=False):
    c = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name=name,
        phone="13800000099", email="t@x.com",
        pdf_path="data/x.pdf", intake_status="complete",
        skills="Python", education="本科",
        bachelor_school="清华大学", school_tier="985",
        work_years=3, seniority="中级",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    for k in HARD_SLOT_KEYS:
        session.add(IntakeSlot(
            candidate_id=c.id, slot_key=k, slot_category="hard",
            value="filled", ask_count=1,
        ))
    if with_promoted_resume:
        r = Resume(
            user_id=user_id, name=name, boss_id=boss_id,
            phone="13800000099", email="t@x.com",
            skills="Python", education="本科",
            bachelor_school="清华大学",
            work_years=3, seniority="中级",
            ai_parsed="yes", source="boss_zhipin",
            pdf_path="data/x.pdf", status="passed",
        )
        session.add(r)
        session.commit()
        c.promoted_resume_id = r.id
    session.commit()
    session.refresh(c)
    return c


# ─── /api/resumes/{candidate.id} ────────────────────────────────────


def test_get_resume_by_candidate_id(client, db_session):
    c = _seed_candidate(db_session, boss_id="b_get", name="GET测试")
    resp = client.get(f"/api/resumes/{c.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "GET测试"
    assert resp.json()["id"] == c.id


def test_patch_resume_by_candidate_id(client, db_session):
    c = _seed_candidate(db_session, boss_id="b_patch", name="原名",
                        with_promoted_resume=True)
    resp = client.patch(f"/api/resumes/{c.id}",
                        json={"name": "新名", "skills": "Go,Python"})
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.name == "新名"
    # 同步到 promoted Resume
    r = db_session.query(Resume).get(c.promoted_resume_id)
    assert r.name == "新名"
    assert r.skills == "Go,Python"


def test_patch_resume_status_synced_to_promoted_resume(client, db_session):
    c = _seed_candidate(db_session, boss_id="b_patchst",
                        with_promoted_resume=True)
    resp = client.patch(f"/api/resumes/{c.id}", json={"status": "rejected"})
    assert resp.status_code == 200
    db_session.expire_all()
    r = db_session.query(Resume).get(c.promoted_resume_id)
    assert r.status == "rejected"


def test_delete_resume_by_candidate_id_cascades(client, db_session):
    c = _seed_candidate(db_session, boss_id="b_del",
                        with_promoted_resume=True)
    cid = c.id
    rid = c.promoted_resume_id
    resp = client.delete(f"/api/resumes/{cid}")
    assert resp.status_code == 204
    db_session.expire_all()
    assert db_session.query(IntakeCandidate).get(cid) is None
    assert db_session.query(Resume).get(rid) is None
    assert db_session.query(IntakeSlot).filter_by(candidate_id=cid).count() == 0


# ─── ai-parse ───────────────────────────────────────────────────────


def test_ai_parse_by_candidate_id_writes_both_models(client, db_session, monkeypatch):
    c = _seed_candidate(db_session, boss_id="b_ai", name="解析测试",
                        with_promoted_resume=True)
    c.raw_text = "姓名：解析测试\n技能：Java, Spring\n本科：清华大学\n"
    db_session.commit()
    r = db_session.query(Resume).get(c.promoted_resume_id)
    r.raw_text = c.raw_text
    db_session.commit()

    parsed_payload = {
        "name": "解析测试", "skills": "Java,Spring",
        "bachelor_school": "清华大学", "education": "本科",
        "work_years": 3, "seniority": "中级",
    }

    async def _fake_parse(*_a, **_k):
        return parsed_payload

    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "ai_enabled", True, raising=False)
    with patch("app.modules.resume.pdf_parser.ai_parse_resume", _fake_parse), \
         patch("app.modules.resume.pdf_parser.ai_parse_resume_vision", _fake_parse), \
         patch("app.modules.resume.pdf_parser.is_image_pdf", lambda _p: False), \
         patch("app.adapters.ai_provider.AIProvider.is_configured", lambda self: True):
        resp = client.post(f"/api/resumes/{c.id}/ai-parse")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["skills"] == "Java,Spring"
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.ai_parsed == "yes"
    assert cand.skills == "Java,Spring"
    r = db_session.query(Resume).get(cand.promoted_resume_id)
    assert r.ai_parsed == "yes"
    assert r.skills == "Java,Spring"


def test_ai_parse_auto_promotes_when_no_resume(client, db_session, monkeypatch):
    """候选人无 promoted_resume_id 时，ai-parse 自动 promote 出 Resume 行。"""
    c = _seed_candidate(db_session, boss_id="b_ai_promote",
                        with_promoted_resume=False)
    c.raw_text = "姓名：自动promote\n技能：Rust\n"
    db_session.commit()
    assert c.promoted_resume_id is None

    async def _fake_parse(*_a, **_k):
        return {"name": "自动promote", "skills": "Rust"}

    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "ai_enabled", True, raising=False)
    with patch("app.modules.resume.pdf_parser.ai_parse_resume", _fake_parse), \
         patch("app.modules.resume.pdf_parser.ai_parse_resume_vision", _fake_parse), \
         patch("app.modules.resume.pdf_parser.is_image_pdf", lambda _p: False), \
         patch("app.adapters.ai_provider.AIProvider.is_configured", lambda self: True):
        resp = client.post(f"/api/resumes/{c.id}/ai-parse")

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.promoted_resume_id is not None
    r = db_session.query(Resume).get(cand.promoted_resume_id)
    assert r.skills == "Rust"


# ─── /api/matching ──────────────────────────────────────────────────


def test_matching_results_by_candidate_id(client, db_session):
    """前端 viewResume → matchingApi.listByResume(candidate.id)。"""
    c = _seed_candidate(db_session, boss_id="b_match",
                        with_promoted_resume=True)
    job = Job(
        title="测试岗位", user_id=1, is_active=True,
        competency_model={"hard_skills": [], "experience": {"years_min": 0},
                          "education": {}, "job_level": "中级"},
        competency_model_status="approved",
    )
    db_session.add(job)
    db_session.commit()
    db_session.add(MatchingResult(
        resume_id=c.promoted_resume_id, job_id=job.id,
        total_score=80.0, skill_score=80.0, experience_score=80.0,
        seniority_score=80.0, education_score=80.0, industry_score=80.0,
        hard_gate_passed=True, scored_at=datetime.now(timezone.utc),
        competency_hash="h1", weights_hash="w1",
        evidence="{}", missing_must_haves="[]", tags="[]",
    ))
    db_session.commit()

    resp = client.get(f"/api/matching/results?resume_id={c.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


def test_matching_recompute_by_candidate_id(client, db_session):
    c = _seed_candidate(db_session, boss_id="b_rec",
                        with_promoted_resume=True)
    resp = client.post("/api/matching/recompute", json={"resume_id": c.id})
    assert resp.status_code == 200, resp.text
    assert "task_id" in resp.json()


def test_matching_recompute_auto_promotes(client, db_session):
    """候选人首次评分自动 promote。"""
    c = _seed_candidate(db_session, boss_id="b_recprom",
                        with_promoted_resume=False)
    assert c.promoted_resume_id is None
    resp = client.post("/api/matching/recompute", json={"resume_id": c.id})
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.promoted_resume_id is not None


# ─── /api/scheduling/interviews ─────────────────────────────────────


def test_create_interview_by_candidate_id_translates_to_resume_id(
    client, db_session, monkeypatch
):
    # 先塞几条 Resume 占据低 id，让 candidate.id 与 promoted_resume_id 数值不同
    for i in range(5):
        db_session.add(Resume(user_id=1, name=f"占位{i}", phone=f"1390{i:07d}"))
    db_session.commit()
    c = _seed_candidate(db_session, boss_id="b_iv",
                        with_promoted_resume=True)
    interviewer = Interviewer(
        user_id=1, name="面试官", phone="13900000099",
        email="iv@x.com",
    )
    db_session.add(interviewer)
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    resp = client.post("/api/scheduling/interviews", json={
        "resume_id": c.id,
        "interviewer_id": interviewer.id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Interview 表存 Resume.id（不是 candidate.id）
    assert body["resume_id"] == c.promoted_resume_id
    assert body["resume_id"] != c.id

    db_session.expire_all()
    iv = db_session.query(Interview).get(body["id"])
    assert iv.resume_id == c.promoted_resume_id


def test_create_interview_auto_promotes_unpromoted_candidate(
    client, db_session
):
    c = _seed_candidate(db_session, boss_id="b_iv_prom",
                        with_promoted_resume=False)
    interviewer = Interviewer(
        user_id=1, name="面试官A", phone="13900000098",
        email="iva@x.com",
    )
    db_session.add(interviewer)
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    resp = client.post("/api/scheduling/interviews", json={
        "resume_id": c.id,
        "interviewer_id": interviewer.id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    })
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    cand = db_session.query(IntakeCandidate).get(c.id)
    assert cand.promoted_resume_id is not None
    assert resp.json()["resume_id"] == cand.promoted_resume_id


def test_create_interview_unknown_id_returns_404(client, db_session):
    interviewer = Interviewer(
        user_id=1, name="面试官B", phone="13900000097",
        email="ivb@x.com",
    )
    db_session.add(interviewer)
    db_session.commit()
    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = start + timedelta(hours=1)
    resp = client.post("/api/scheduling/interviews", json={
        "resume_id": 999999,
        "interviewer_id": interviewer.id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    })
    assert resp.status_code == 404
