"""F2 排序正确性测试 — 多简历 × 多岗位."""
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
)
HIGH_VEC = patch(
    "app.modules.matching.scorers.skill._max_vector_similarity",
    return_value=0.95,
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


def _mk_job(session, cm=None, **kw):
    defaults = dict(
        title="岗位", is_active=True, required_skills="",
        competency_model=cm or {
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


@pytest.mark.asyncio
async def test_ranking_10_resumes_known_order(db_session, client):
    """10 份简历已知相对强弱 → 打分 → list_results 顺序与预期一致."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 3, "years_max": 8},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    })

    # 工作年限从 1 到 10，对应 score 从低到高（年限 3-8 满分，超出/不足扣分）
    # 职级全部"高级"与岗位完全匹配（seniority=100）
    resumes = []
    for i in range(1, 11):
        r = _mk_resume(
            db_session,
            name=f"候选人_{i}年",
            work_years=i,
            seniority="高级",
            skills="Python",
        )
        resumes.append(r)

    with NO_LLM:
        for r in resumes:
            await MatchingService(db_session).score_pair(r.id, job.id, triggered_by="T1")

    resp = client.get(f"/api/matching/results?job_id={job.id}&page_size=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 10

    scores = [it["total_score"] for it in data["items"]]
    # 验证降序排列
    assert scores == sorted(scores, reverse=True)

    # 年限 3-8 的候选人应排在最前面（满分区间）
    top_names = [it["resume_name"] for it in data["items"][:5]]
    in_range_count = sum(
        1 for n in top_names
        if any(f"_{y}年" in n for y in range(3, 9))
    )
    assert in_range_count >= 4


@pytest.mark.asyncio
async def test_ranking_one_resume_five_jobs(db_session, client):
    """1 份简历 × 5 个岗位 → listByResume 返回全部 5 条，分数合理."""
    resume = _mk_resume(
        db_session, name="通用候选人", work_years=5,
        seniority="高级", skills="Python, Go",
    )

    job_ids = []
    for i in range(5):
        j = _mk_job(db_session, cm={
            "hard_skills": [],
            "experience": {"years_min": i, "years_max": i + 5},
            "education": {},
            "job_level": "高级",
        }, title=f"岗位{i}")
        job_ids.append(j.id)

    with NO_LLM:
        for jid in job_ids:
            await MatchingService(db_session).score_pair(resume.id, jid, triggered_by="T2")

    resp = client.get(f"/api/matching/results?resume_id={resume.id}&page_size=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    # 所有分数必须在合法区间
    for item in data["items"]:
        assert 0 <= item["total_score"] <= 100


@pytest.mark.asyncio
async def test_ranking_ties_deterministic(db_session):
    """两份字段完全相同的简历对同一岗位打分 → 分数完全一致（确定性）."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 3, "years_max": 8},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    })
    r1 = _mk_resume(db_session, name="双胞胎A", work_years=5, seniority="高级", education="本科")
    r2 = _mk_resume(db_session, name="双胞胎B", work_years=5, seniority="高级", education="本科")

    with NO_LLM:
        res1 = await MatchingService(db_session).score_pair(r1.id, job.id)
        res2 = await MatchingService(db_session).score_pair(r2.id, job.id)

    assert res1.total_score == res2.total_score
    assert res1.skill_score == res2.skill_score
    assert res1.experience_score == res2.experience_score
    assert res1.seniority_score == res2.seniority_score
    assert res1.education_score == res2.education_score


@pytest.mark.asyncio
async def test_ranking_score_order_matches_db_order(db_session, client):
    """API 返回结果顺序与 DB 中降序一致."""
    job = _mk_job(db_session)
    # 手动插入不同分值行（直接写 DB，绕过 scorer）
    for score in [45.0, 90.0, 72.5, 30.0, 60.0]:
        r = _mk_resume(db_session, name=f"候选人_{score}")
        row = MatchingResult(
            resume_id=r.id, job_id=job.id,
            total_score=score, skill_score=score,
            experience_score=score, seniority_score=score,
            education_score=score, industry_score=score,
            hard_gate_passed=1, missing_must_haves="[]",
            evidence="{}", tags='["中匹配"]',
            competency_hash="same", weights_hash="same",
            scored_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
    db_session.commit()

    # seed 给了 hash "same"，但 job competency_model 实际 hash 不同 → stale=True
    # 只验证顺序
    resp = client.get(f"/api/matching/results?job_id={job.id}&page_size=100")
    assert resp.status_code == 200
    data = resp.json()
    scores = [it["total_score"] for it in data["items"]]
    assert scores == sorted(scores, reverse=True)
