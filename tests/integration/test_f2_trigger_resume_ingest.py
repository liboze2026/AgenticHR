import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.triggers import on_resume_parsed
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _mk_open_job(session, title="Job"):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    j = Job(title=title, is_active=True, required_skills="",
            competency_model=cm, competency_model_status="approved")
    session.add(j); session.commit()
    return j


@pytest.mark.asyncio
async def test_on_resume_parsed_scores_all_open_approved_jobs(db_session):
    _mk_open_job(db_session, "Job A")
    _mk_open_job(db_session, "Job B")
    # 未发布的能力模型不应被打分
    unapproved = Job(title="Draft", is_active=True, required_skills="",
                     competency_model={"hard_skills": []}, competency_model_status="draft")
    db_session.add(unapproved); db_session.commit()
    # is_active=False 的岗位不应被打分
    closed = Job(title="Closed", is_active=False, required_skills="",
                 competency_model={"hard_skills": []}, competency_model_status="approved")
    db_session.add(closed); db_session.commit()

    r = Resume(name="张三", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_resume_parsed(db_session, r.id)

    rows = db_session.query(MatchingResult).filter_by(resume_id=r.id).all()
    assert len(rows) == 2  # 只有 is_active + approved 的两个
