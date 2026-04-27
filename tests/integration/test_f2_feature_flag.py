"""F2 matching_enabled 功能开关测试."""
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.triggers import on_resume_parsed, on_competency_approved
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
)


def _mk_resume(session, **kw):
    defaults = dict(
        name="候选人", phone="", skills="Python",
        work_years=3, education="本科", seniority="中级",
        ai_parsed="yes", source="manual", user_id=1,
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, **kw):
    defaults = dict(
        title="岗位", is_active=True, required_skills="",
        competency_model={
            "hard_skills": [],
            "experience": {"years_min": 0},
            "education": {},
            "job_level": "中级",
        },
        competency_model_status="approved",
        user_id=1,
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


def test_score_returns_503_when_disabled(db_session, client, monkeypatch):
    """/score 在 matching_enabled=False 时返回 503."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    resp = client.post("/api/matching/score", json={"resume_id": resume.id, "job_id": job.id})
    assert resp.status_code == 503


def test_results_returns_503_when_disabled(db_session, client, monkeypatch):
    """/results 在 matching_enabled=False 时返回 503."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    job = _mk_job(db_session)
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 503


def test_recompute_returns_503_when_disabled(db_session, client, monkeypatch):
    """/recompute 在 matching_enabled=False 时返回 503."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    job = _mk_job(db_session)
    resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 503


def test_endpoints_work_after_re_enable(db_session, client, monkeypatch):
    """matching_enabled 恢复 True 后，endpoints 正常工作."""
    from app.config import settings

    # 先禁用
    monkeypatch.setattr(settings, "matching_enabled", False)
    job = _mk_job(db_session)
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 503

    # 恢复
    monkeypatch.setattr(settings, "matching_enabled", True)
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_t1_silently_returns_when_disabled(db_session, monkeypatch):
    """T1 在 matching_enabled=False 时静默返回, 不建行, 不抛异常."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    _mk_job(db_session)
    resume = _mk_resume(db_session)

    with NO_LLM:
        await on_resume_parsed(db_session, resume.id)  # 不应抛

    rows = db_session.query(MatchingResult).filter_by(resume_id=resume.id).all()
    assert rows == []


@pytest.mark.asyncio
async def test_t2_silently_returns_when_disabled(db_session, monkeypatch):
    """T2 在 matching_enabled=False 时静默返回, 不建行, 不抛异常."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    job = _mk_job(db_session)
    _mk_resume(db_session)

    with NO_LLM:
        await on_competency_approved(db_session, job.id)  # 不应抛

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert rows == []
