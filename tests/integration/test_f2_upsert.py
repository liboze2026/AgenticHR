import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_same_pair_single_row(db_session):
    j = Job(title="J", is_active=True, required_skills="",
            competency_model={"hard_skills": [], "experience": {}, "education": {}, "job_level": ""},
            competency_model_status="approved")
    db_session.add(j); db_session.commit()
    r = Resume(name="R", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    service = MatchingService(db_session)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await service.score_pair(r.id, j.id)
        await service.score_pair(r.id, j.id)
        await service.score_pair(r.id, j.id)

    count = db_session.query(MatchingResult).filter_by(
        resume_id=r.id, job_id=j.id
    ).count()
    assert count == 1
