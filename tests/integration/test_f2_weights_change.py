"""F2 评分权重变更测试."""
import json
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
)


def _mk_resume(session, **kw):
    defaults = dict(
        name="候选人", phone="", skills="Python",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
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
            "experience": {"years_min": 3, "years_max": 8},
            "education": {"min_level": "本科"},
            "job_level": "高级",
        },
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


@pytest.fixture(autouse=True)
def restore_weights():
    """每个测试后清理自定义权重文件, 确保测试隔离."""
    from app.core.settings.router import _CONFIG_PATH
    yield
    if _CONFIG_PATH.exists():
        _CONFIG_PATH.unlink()


def _write_weights(weights: dict):
    from app.core.settings.router import _CONFIG_PATH
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(weights), encoding="utf-8")


@pytest.mark.asyncio
async def test_weights_change_stale_and_recompute(db_session, client):
    """变更权重 → 现有行变 stale → 重打分 → weights_hash 更新, stale 消除."""
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    # 用默认权重打分
    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id)

    row1 = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
    old_weights_hash = row1.weights_hash

    # 修改权重（技能占比提高）
    _write_weights({"skill_match": 60, "experience": 20, "seniority": 10, "education": 5, "industry": 5})

    # GET /results → stale=True (因 weights_hash 不同)
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    data = resp.json()
    assert resp.status_code == 200
    assert data["items"][0]["stale"] is True

    # 重打分
    with NO_LLM:
        r2 = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert r2.stale is False

    # DB 行 weights_hash 已更新
    db_session.expire_all()
    row2 = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
    assert row2.weights_hash != old_weights_hash


@pytest.mark.asyncio
async def test_weights_change_makes_all_5_jobs_stale(db_session, client):
    """5 个岗位 + 1 简历打分后变更权重 → 5 行全部 stale."""
    resume = _mk_resume(db_session)
    jobs = [_mk_job(db_session, title=f"Job{i}") for i in range(5)]

    with NO_LLM:
        for j in jobs:
            await MatchingService(db_session).score_pair(resume.id, j.id)

    # 修改权重
    _write_weights({"skill_match": 50, "experience": 20, "seniority": 15, "education": 10, "industry": 5})

    # 查每个 job 的结果
    stale_count = 0
    for j in jobs:
        resp = client.get(f"/api/matching/results?job_id={j.id}")
        data = resp.json()
        if data["items"] and data["items"][0]["stale"]:
            stale_count += 1

    assert stale_count == 5


@pytest.mark.asyncio
async def test_weights_hash_updated_after_recompute(db_session):
    """重打分后 DB 行的 weights_hash 确实变更."""
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id)

    row_before = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    hash_before = row_before.weights_hash

    # 切换权重
    _write_weights({"skill_match": 40, "experience": 25, "seniority": 15, "education": 10, "industry": 10})

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id)

    db_session.expire_all()
    row_after = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    assert row_after.weights_hash != hash_before
