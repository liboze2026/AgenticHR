from unittest.mock import patch, AsyncMock


def test_score_endpoint_returns_result(client, db_session):
    from app.modules.resume.models import Resume
    from app.modules.screening.models import Job
    resume = Resume(name="张三", phone="13900000001", email="t@test.com",
                    skills="Python", work_years=5, education="本科",
                    ai_parsed="yes", source="manual", seniority="高级", user_id=1)
    db_session.add(resume); db_session.commit()
    cm = {"hard_skills": [], "experience": {"years_min": 3, "years_max": 8},
          "education": {"min_level": "本科"}, "job_level": "高级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved", user_id=1)
    db_session.add(job); db_session.commit()

    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/score",
                            json={"resume_id": resume.id, "job_id": job.id})

    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_id"] == resume.id
    assert data["job_id"] == job.id
    assert "total_score" in data
    assert "evidence" in data


def test_score_endpoint_403_on_missing(client):
    resp = client.post("/api/matching/score", json={"resume_id": 99999, "job_id": 99999})
    assert resp.status_code == 403
