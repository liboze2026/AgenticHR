import time
from unittest.mock import patch, AsyncMock
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _seed(session, n_resumes=3):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved", user_id=1)
    session.add(job); session.commit()

    for i in range(n_resumes):
        r = Resume(name=f"R{i}", phone="", skills="Python", work_years=2,
                   education="本科", ai_parsed="yes", source="manual", seniority="中级", user_id=1)
        session.add(r); session.commit()
    return job


def test_recompute_job_returns_task_id(client, db_session):
    job = _seed(db_session, n_resumes=2)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["total"] >= 2


def test_recompute_status_endpoint(client, db_session):
    job = _seed(db_session, n_resumes=1)
    with patch("app.modules.matching.service.enhance_evidence_with_llm",
               new=AsyncMock(side_effect=lambda ev, *a, **kw: ev)):
        resp = client.post("/api/matching/recompute", json={"job_id": job.id})
    task_id = resp.json()["task_id"]

    # Wait briefly for background task
    time.sleep(0.1)
    status_resp = client.get(f"/api/matching/recompute/status/{task_id}")
    assert status_resp.status_code == 200
    s = status_resp.json()
    assert s["task_id"] == task_id
    assert s["total"] >= 1


def test_recompute_validates_one_of(client):
    resp = client.post("/api/matching/recompute", json={})
    assert resp.status_code == 400
