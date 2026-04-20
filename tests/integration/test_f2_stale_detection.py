import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


@pytest.mark.asyncio
async def test_stale_after_competency_change(db_session, client):
    cm_v1 = {"hard_skills": [], "experience": {"years_min": 0},
             "education": {}, "job_level": "中级"}
    j = Job(title="J", is_active=True, required_skills="",
            competency_model=cm_v1, competency_model_status="approved")
    db_session.add(j); db_session.commit()
    r = Resume(name="R", phone="", skills="Python", work_years=3,
               education="本科", ai_parsed="yes", source="manual", seniority="中级")
    db_session.add(r); db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        await MatchingService(db_session).score_pair(r.id, j.id)

    # 修改能力模型
    j.competency_model = {**cm_v1, "hard_skills": [{"name": "Go", "weight": 10}]}
    db_session.commit()
    db_session.expire_all()

    resp = client.get(f"/api/matching/results?job_id={j.id}")
    data = resp.json()
    assert data["items"][0]["stale"] is True
