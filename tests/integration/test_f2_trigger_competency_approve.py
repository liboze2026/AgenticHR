import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.triggers import on_competency_approved
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_on_competency_approved_scores_recent_resumes(db_session):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    j = Job(title="后端", is_active=True, required_skills="",
            competency_model=cm, competency_model_status="approved")
    db_session.add(j); db_session.commit()

    # 最近 30 天内的简历
    recent = Resume(name="Recent", phone="", skills="Python", work_years=3,
                    education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(recent); db_session.commit()

    # 老于 90 天的简历（手动调 created_at）
    old = Resume(name="Old", phone="", skills="Python", work_years=3,
                 education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(old); db_session.commit()
    old.created_at = datetime.now(timezone.utc) - timedelta(days=120)
    db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await on_competency_approved(db_session, j.id)

    rows = db_session.query(MatchingResult).filter_by(job_id=j.id).all()
    assert len(rows) == 1
    assert rows[0].resume_id == recent.id
