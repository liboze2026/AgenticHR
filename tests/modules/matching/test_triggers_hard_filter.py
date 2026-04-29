"""T1/T2 触发器硬筛守卫测试.

防止 "再次分析" 清掉硬筛失败行后, T1/T2 又把它们写回。
"""
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.triggers import on_resume_parsed, on_competency_approved
from app.modules.resume.models import Resume
from app.modules.screening.models import Job
from app.modules.im_intake.candidate_model import IntakeCandidate
from app.modules.im_intake.models import IntakeSlot
from app.modules.im_intake.templates import HARD_SLOT_KEYS


def _seed_user1(db):
    """conftest 已 seed users 0/1/2。"""
    pass


def _make_job(db, education_min="", school_tier_min="", user_id=1):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    j = Job(
        title="后端", is_active=True, required_skills="",
        competency_model=cm, competency_model_status="approved",
        user_id=user_id, education_min=education_min,
        school_tier_min=school_tier_min,
    )
    db.add(j); db.commit()
    return j


def _make_complete(db, education="本科", school_tier="985",
                   boss_id="b1", user_id=1):
    cand = IntakeCandidate(
        user_id=user_id, boss_id=boss_id, name="x",
        pdf_path=f"data/{boss_id}.pdf", intake_status="complete",
        education=education, school_tier=school_tier, source="manual",
    )
    db.add(cand); db.commit(); db.refresh(cand)
    for k in HARD_SLOT_KEYS:
        db.add(IntakeSlot(
            candidate_id=cand.id, slot_key=k, slot_category="hard",
            value="x", ask_count=1,
        ))
    r = Resume(
        name="x", phone="", skills="Python", work_years=2,
        education=education, ai_parsed="yes", source="manual",
        seniority="中级", user_id=user_id, boss_id=boss_id,
        intake_candidate_id=cand.id,
    )
    db.add(r); db.commit()
    cand.promoted_resume_id = r.id
    db.commit()
    return cand, r


@pytest.mark.asyncio
async def test_t1_skips_resume_failing_hard_filter(db_session):
    """T1: 学历不达标的 resume 入库, 不应写 matching_results."""
    job = _make_job(db_session, education_min="硕士")
    _, r = _make_complete(db_session, education="本科", boss_id="b1")

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_resume_parsed(db_session, r.id)

    assert db_session.query(MatchingResult).filter_by(
        resume_id=r.id, job_id=job.id,
    ).count() == 0


@pytest.mark.asyncio
async def test_t1_writes_for_resume_passing_hard_filter(db_session):
    """T1: 硬筛通过的 resume 正常打分."""
    job = _make_job(db_session, education_min="本科")
    _, r = _make_complete(db_session, education="硕士", boss_id="b1")

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_resume_parsed(db_session, r.id)

    assert db_session.query(MatchingResult).filter_by(
        resume_id=r.id, job_id=job.id,
    ).count() == 1


@pytest.mark.asyncio
async def test_t2_skips_resumes_failing_hard_filter(db_session):
    """T2: 能力模型发布触发, 仅对硬筛通过的 resume 打分."""
    job = _make_job(db_session, education_min="硕士")
    _, r_pass = _make_complete(db_session, education="硕士", boss_id="ok")
    _, r_fail = _make_complete(db_session, education="本科", boss_id="bad")

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_competency_approved(db_session, job.id)

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    surviving = {row.resume_id for row in rows}
    assert r_pass.id in surviving
    assert r_fail.id not in surviving
