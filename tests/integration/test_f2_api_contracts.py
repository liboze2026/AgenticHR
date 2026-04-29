"""F2 API 契约边界测试."""
import pytest
import uuid
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone
from app.modules.matching.models import MatchingResult
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
        ai_parsed="yes", source="manual", user_id=1,
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, **kw):
    defaults = dict(
        title="岗位", is_active=True, required_skills="",
        competency_model={
            "hard_skills": [],
            "experience": {"years_min": 0},
            "education": {},
            "job_level": "中级",
        },
        competency_model_status="approved",
        user_id=1,
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


def test_results_nonexistent_job_returns_404(client):
    """/results?job_id=999999 → 404；他人资源与不存在均返 404，不暴露存在性（BUG-056）."""
    resp = client.get("/api/matching/results?job_id=999999")
    assert resp.status_code == 404


def test_results_no_filter_returns_400(client, db_session):
    """/results 既无 job_id 也无 resume_id → 400."""
    _mk_job(db_session)
    resp = client.get("/api/matching/results")
    assert resp.status_code == 400


def test_results_nonexistent_tag_returns_empty(client, db_session):
    """/results?tag=不存在的标签 → {total: 0, items: []}."""
    job = _mk_job(db_session)
    # 先插入一行数据
    r = _mk_resume(db_session)
    db_session.add(MatchingResult(
        resume_id=r.id, job_id=job.id,
        total_score=75.0, skill_score=75.0,
        experience_score=80.0, seniority_score=80.0,
        education_score=80.0, industry_score=80.0,
        hard_gate_passed=1, missing_must_haves="[]",
        evidence="{}", tags='["高匹配"]',
        competency_hash="h1", weights_hash="h2",
        scored_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    resp = client.get(f"/api/matching/results?job_id={job.id}&tag=不存在的标签")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_results_page_size_over_100_returns_422(client, db_session):
    """/results?page_size=101 → 422 validation."""
    job = _mk_job(db_session)
    resp = client.get(f"/api/matching/results?job_id={job.id}&page_size=101")
    assert resp.status_code == 422


def test_results_page_size_zero_returns_422(client, db_session):
    """/results?page_size=0 → 422 validation."""
    job = _mk_job(db_session)
    resp = client.get(f"/api/matching/results?job_id={job.id}&page_size=0")
    assert resp.status_code == 422


def test_results_page_zero_returns_422(client, db_session):
    """/results?page=0 → 422 validation."""
    job = _mk_job(db_session)
    resp = client.get(f"/api/matching/results?job_id={job.id}&page=0")
    assert resp.status_code == 422


def test_score_missing_resume_returns_404(client, db_session):
    """/score 简历 ID 不存在 → 404（统一不暴露存在性，BUG-056）."""
    job = _mk_job(db_session)
    resp = client.post("/api/matching/score", json={"resume_id": 999999, "job_id": job.id})
    assert resp.status_code == 404


def test_score_job_no_competency_returns_404(client, db_session):
    """/score 岗位无 competency_model → 404 (ValueError path)."""
    resume = _mk_resume(db_session)
    # 岗位没有 competency_model，但属于同一用户
    j = Job(
        title="无模型岗位", is_active=True, required_skills="",
        competency_model=None,
        competency_model_status="approved",
        user_id=1,
    )
    db_session.add(j)
    db_session.commit()

    resp = client.post("/api/matching/score", json={"resume_id": resume.id, "job_id": j.id})
    assert resp.status_code == 404


def test_recompute_with_both_ids_takes_job_branch(client, db_session):
    """/recompute 同时传 job_id 和 resume_id → 走 job 分支（按优先级）."""
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    resp = client.post("/api/matching/recompute", json={"job_id": job.id, "resume_id": resume.id})
    assert resp.status_code == 200
    data = resp.json()
    # job 分支返回 task_id
    assert "task_id" in data


def test_recompute_status_invalid_uuid_returns_404(client):
    """/recompute/status/<invalid-uuid> → 404."""
    resp = client.get(f"/api/matching/recompute/status/{uuid.uuid4()}-invalid-extra")
    assert resp.status_code == 404


def test_results_pagination_last_page(client, db_session):
    """分页: 5 条数据, page=3, page_size=2 → 1 条结果."""
    job = _mk_job(db_session)
    for i in range(5):
        r = _mk_resume(db_session, name=f"候选人{i}")
        db_session.add(MatchingResult(
            resume_id=r.id, job_id=job.id,
            total_score=float(50 + i), skill_score=50.0,
            experience_score=80.0, seniority_score=80.0,
            education_score=80.0, industry_score=80.0,
            hard_gate_passed=1, missing_must_haves="[]",
            evidence="{}", tags='["中匹配"]',
            competency_hash="h", weights_hash="h",
            scored_at=datetime.now(timezone.utc),
        ))
    db_session.commit()

    resp = client.get(f"/api/matching/results?job_id={job.id}&page=3&page_size=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 1
