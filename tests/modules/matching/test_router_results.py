from datetime import datetime, timezone
from app.modules.matching.models import MatchingResult
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _seed_data(session, count: int = 3):
    cm = {"hard_skills": [], "experience": {"years_min": 0},
          "education": {}, "job_level": "中级"}
    job = Job(title="后端", is_active=True, required_skills="",
              competency_model=cm, competency_model_status="approved")
    session.add(job); session.commit()

    for i in range(count):
        r = Resume(name=f"候选人{i}", phone="13900000000",
                   skills="Python", work_years=3, education="本科",
                   ai_parsed="yes", source="manual", seniority="中级")
        session.add(r); session.commit()
        session.add(MatchingResult(
            resume_id=r.id, job_id=job.id,
            total_score=90 - i * 10, skill_score=90 - i * 10,
            experience_score=80, seniority_score=80, education_score=80, industry_score=80,
            hard_gate_passed=1, missing_must_haves="[]",
            evidence="{}", tags='["中匹配"]',
            competency_hash="h1", weights_hash="h2",
            scored_at=datetime.now(timezone.utc),
        )); session.commit()
    return job


def test_results_by_job_sorted_desc(client, db_session):
    job = _seed_data(db_session, count=3)
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    scores = [it["total_score"] for it in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_results_by_resume(client, db_session):
    _seed_data(db_session, count=1)
    resume_id = db_session.query(MatchingResult).first().resume_id
    resp = client.get(f"/api/matching/results?resume_id={resume_id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_results_filter_by_tag(client, db_session):
    _seed_data(db_session, count=3)
    resp = client.get("/api/matching/results?job_id=1&tag=中匹配")
    assert resp.status_code == 200
    assert resp.json()["total"] == 3


def test_results_pagination(client, db_session):
    _seed_data(db_session, count=5)
    resp = client.get("/api/matching/results?job_id=1&page=1&page_size=2")
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1


def test_stale_flag_true_when_hash_mismatch(client, db_session):
    job = _seed_data(db_session, count=1)
    # seed 用的 "h1" 与当前 competency_model 的 hash 不等 → stale
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    data = resp.json()
    assert data["items"][0]["stale"] is True
