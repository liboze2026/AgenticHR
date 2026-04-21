"""F2 触发器边界条件测试."""
import pytest
from datetime import datetime, timedelta, timezone
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
        ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, cm=None, **kw):
    defaults = dict(
        title="岗位", is_active=True, required_skills="",
        competency_model=cm or {
            "hard_skills": [],
            "experience": {"years_min": 0},
            "education": {},
            "job_level": "中级",
        },
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


@pytest.mark.asyncio
async def test_t1_skips_inactive_jobs(db_session):
    """T1 只对 is_active=True 的岗位打分: 3 inactive + 2 active → 2 行."""
    for i in range(3):
        _mk_job(db_session, title=f"Inactive{i}", is_active=False)
    for i in range(2):
        _mk_job(db_session, title=f"Active{i}", is_active=True)

    resume = _mk_resume(db_session)

    with NO_LLM:
        await on_resume_parsed(db_session, resume.id)

    rows = db_session.query(MatchingResult).filter_by(resume_id=resume.id).all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_t1_skips_non_approved_status(db_session):
    """T1 跳过 competency_model_status in ('none', 'draft')."""
    _mk_job(db_session, title="NoneStatus", competency_model_status="none")
    _mk_job(db_session, title="DraftStatus", competency_model_status="draft")
    _mk_job(db_session, title="ApprovedStatus", competency_model_status="approved")

    resume = _mk_resume(db_session)

    with NO_LLM:
        await on_resume_parsed(db_session, resume.id)

    rows = db_session.query(MatchingResult).filter_by(resume_id=resume.id).all()
    assert len(rows) == 1  # 仅 approved


@pytest.mark.asyncio
async def test_t1_no_jobs_no_exception(db_session):
    """T1 无匹配岗位 → 不建行, 不抛异常."""
    resume = _mk_resume(db_session)

    with NO_LLM:
        await on_resume_parsed(db_session, resume.id)  # 不应抛

    rows = db_session.query(MatchingResult).filter_by(resume_id=resume.id).all()
    assert rows == []


@pytest.mark.asyncio
async def test_t1_disabled_when_matching_disabled(db_session, monkeypatch):
    """matching_enabled=False → T1 直接返回, 不建行."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    _mk_job(db_session)
    resume = _mk_resume(db_session)

    with NO_LLM:
        await on_resume_parsed(db_session, resume.id)

    rows = db_session.query(MatchingResult).filter_by(resume_id=resume.id).all()
    assert rows == []


@pytest.mark.asyncio
async def test_t2_empty_resume_library_no_exception(db_session):
    """T2 简历库为空 → 不建行, 不抛异常."""
    job = _mk_job(db_session)

    with NO_LLM:
        await on_competency_approved(db_session, job.id)  # 不应抛

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert rows == []


@pytest.mark.asyncio
async def test_t2_90_day_boundary(db_session):
    """T2 窗口边界: 89 天 → 包含; 91 天 → 排除."""
    job = _mk_job(db_session)
    now = datetime.now(timezone.utc)

    r_in = _mk_resume(db_session, name="In89Days")
    r_in.created_at = now - timedelta(days=89)
    db_session.commit()

    r_out = _mk_resume(db_session, name="Out91Days")
    r_out.created_at = now - timedelta(days=91)
    db_session.commit()

    with NO_LLM:
        await on_competency_approved(db_session, job.id)

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    resume_ids = {r.resume_id for r in rows}
    assert r_in.id in resume_ids
    assert r_out.id not in resume_ids


@pytest.mark.asyncio
async def test_t2_skips_non_parsed_resumes(db_session):
    """T2 跳过 ai_parsed in ('no', 'parsing', 'failed')."""
    job = _mk_job(db_session)

    _mk_resume(db_session, name="NotParsed", ai_parsed="no")
    _mk_resume(db_session, name="Parsing", ai_parsed="parsing")
    _mk_resume(db_session, name="Failed", ai_parsed="failed")
    r_yes = _mk_resume(db_session, name="Parsed", ai_parsed="yes")

    with NO_LLM:
        await on_competency_approved(db_session, job.id)

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert len(rows) == 1
    assert rows[0].resume_id == r_yes.id


@pytest.mark.asyncio
async def test_t2_disabled_when_matching_disabled(db_session, monkeypatch):
    """matching_enabled=False → T2 直接返回, 不建行."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_enabled", False)

    job = _mk_job(db_session)
    _mk_resume(db_session)

    with NO_LLM:
        await on_competency_approved(db_session, job.id)

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert rows == []
