import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from app.modules.matching.service import MatchingService
from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _seed_resume(session, **overrides):
    kw = dict(
        name="张三", phone="13900000001", email="t@test.com",
        skills="Python, Go, FastAPI", work_experience="在某互联网公司任后端 5 年",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
    )
    kw.update(overrides)
    r = Resume(**kw)
    session.add(r); session.commit()
    return r


def _seed_job_with_competency(session, competency_model: dict, **overrides):
    kw = dict(
        title="后端工程师",
        education_min="本科", work_years_min=3, work_years_max=8,
        required_skills="Python",
        competency_model=competency_model,
        competency_model_status="approved",
    )
    kw.update(overrides)
    j = Job(**kw)
    session.add(j); session.commit()
    return j


@pytest.mark.asyncio
async def test_score_pair_writes_row(db_session):
    resume = _seed_resume(db_session)
    cm = {
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 8, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    }
    job = _seed_job_with_competency(db_session, cm)

    service = MatchingService(db_session)
    with patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.95), \
         patch("app.modules.matching.service.enhance_evidence_with_llm", new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        result = await service.score_pair(resume.id, job.id)

    row = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
    assert row.total_score == result.total_score
    assert row.hard_gate_passed == 1
    assert row.skill_score > 0


@pytest.mark.asyncio
async def test_score_pair_upserts(db_session):
    resume = _seed_resume(db_session)
    cm = {"hard_skills": [], "experience": {"years_min": 3, "years_max": 8},
          "education": {"min_level": "本科"}, "job_level": "中级"}
    job = _seed_job_with_competency(db_session, cm)

    service = MatchingService(db_session)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        r1 = await service.score_pair(resume.id, job.id)
        r2 = await service.score_pair(resume.id, job.id)

    count = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).count()
    assert count == 1
    assert r2.id == r1.id


@pytest.mark.asyncio
async def test_score_pair_hard_gate_missing(db_session):
    resume = _seed_resume(db_session, skills="Java")
    cm = {
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 8},
        "education": {"min_level": "本科"}, "job_level": "高级",
    }
    job = _seed_job_with_competency(db_session, cm)

    service = MatchingService(db_session)
    with patch("app.modules.matching.scorers.skill._max_vector_similarity", return_value=0.2), \
         patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        result = await service.score_pair(resume.id, job.id)

    assert result.hard_gate_passed is False
    assert "Python" in result.missing_must_haves
    assert result.total_score <= 29.0


@pytest.mark.asyncio
async def test_score_pair_raises_on_missing_resume(db_session):
    with pytest.raises(ValueError, match="resume"):
        await MatchingService(db_session).score_pair(99999, 1)


@pytest.mark.asyncio
async def test_recompute_job_pre_filter_limits_targets(db_session):
    """recompute_job 接受 pre_filter_resume_ids 时, 仅对集合内简历打分."""
    from app.modules.matching.service import recompute_job, _new_task, _RECOMPUTE_TASKS

    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = _seed_job_with_competency(db_session, cm, user_id=1)

    r1 = _seed_resume(db_session, name="A", user_id=1)
    r2 = _seed_resume(db_session, name="B", user_id=1)
    r3 = _seed_resume(db_session, name="C", user_id=1)

    task_id = _new_task(0)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await recompute_job(
            db_session, job.id, task_id, user_id=1,
            pre_filter_resume_ids={r1.id, r3.id},
        )

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    scored_ids = {r.resume_id for r in rows}
    assert scored_ids == {r1.id, r3.id}
    assert _RECOMPUTE_TASKS[task_id]["completed"] == 2
    assert _RECOMPUTE_TASKS[task_id]["total"] == 2


@pytest.mark.asyncio
async def test_recompute_job_pre_filter_empty_skips_all(db_session):
    """pre_filter_resume_ids=空集合 → 完全跳过, 不打任何分."""
    from app.modules.matching.service import recompute_job, _new_task, _RECOMPUTE_TASKS

    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = _seed_job_with_competency(db_session, cm, user_id=1)
    _seed_resume(db_session, name="A", user_id=1)

    task_id = _new_task(0)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await recompute_job(
            db_session, job.id, task_id, user_id=1,
            pre_filter_resume_ids=set(),
        )

    assert db_session.query(MatchingResult).filter_by(job_id=job.id).count() == 0
    assert _RECOMPUTE_TASKS[task_id]["total"] == 0


@pytest.mark.asyncio
async def test_recompute_job_pre_filter_none_keeps_legacy(db_session):
    """pre_filter_resume_ids=None → 旧行为 (全 ai_parsed=yes 简历打分)."""
    from app.modules.matching.service import recompute_job, _new_task, _RECOMPUTE_TASKS

    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = _seed_job_with_competency(db_session, cm, user_id=1)
    r1 = _seed_resume(db_session, name="A", user_id=1)
    r2 = _seed_resume(db_session, name="B", user_id=1)

    task_id = _new_task(0)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await recompute_job(
            db_session, job.id, task_id, user_id=1,
            pre_filter_resume_ids=None,
        )

    rows = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert {r.resume_id for r in rows} == {r1.id, r2.id}
