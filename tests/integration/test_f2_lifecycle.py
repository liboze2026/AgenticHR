"""F2 全生命周期链条测试."""
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.matching.triggers import on_resume_parsed, on_competency_approved
from app.modules.resume.models import Resume
from app.modules.screening.models import Job


def _mk_resume(session, **kw):
    defaults = dict(
        name="张三", phone="", email="", skills="Python, Go, FastAPI",
        work_experience="在互联网公司做后端 5 年", work_years=5, education="本科",
        seniority="高级", ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, cm=None, **kw):
    default_cm = {
        "hard_skills": [],
        "experience": {"years_min": 3, "years_max": 8, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    }
    cm = cm or default_cm
    defaults = dict(
        title="Job", is_active=True, required_skills="",
        competency_model=cm,
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


NO_LLM = patch(
    "app.modules.matching.service.enhance_evidence_with_llm",
    new=AsyncMock(side_effect=lambda ev, *a, **kw: ev),
)
HIGH_VEC = patch(
    "app.modules.matching.scorers.skill._max_vector_similarity",
    return_value=0.95,
)


@pytest.mark.asyncio
async def test_full_lifecycle_score_edit_recompute(db_session, client):
    """岗位创建 → 能力模型发布 → 简历入库触发打分 → 编辑能力模型 → 过时检测 → 重打分 → 分数更新."""
    # Phase 1: 创建 job + resume
    job = _mk_job(db_session, cm={
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 8},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    })
    resume = _mk_resume(db_session)

    # Phase 2: T1 触发打分
    with NO_LLM, HIGH_VEC:
        await on_resume_parsed(db_session, resume.id)

    row1 = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    score1 = row1.total_score
    hash1 = row1.competency_hash
    assert score1 > 50

    # Phase 3: HR 编辑能力模型（加一个必须项技能，简历里没有）
    job.competency_model = {
        "hard_skills": [
            {"name": "Python", "weight": 10, "must_have": True, "canonical_id": None},
            {"name": "Kubernetes", "weight": 8, "must_have": True, "canonical_id": None},
        ],
        "experience": {"years_min": 3, "years_max": 8},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    }
    db_session.commit()

    # Phase 4: GET /results 看到 stale=True
    resp = client.get(f"/api/matching/results?job_id={job.id}")
    data = resp.json()
    assert resp.status_code == 200
    assert data["items"][0]["stale"] is True
    assert data["items"][0]["total_score"] == score1  # 旧分数未变

    # Phase 5: 手动单对重打分 (T4) — Python 命中(0.95)，K8s 未命中(0.3)
    with NO_LLM, patch(
        "app.modules.matching.scorers.skill._max_vector_similarity",
        side_effect=[0.95, 0.3],
    ):
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.total_score <= 29.0  # hard gate 触发
    assert "Kubernetes" in result.missing_must_haves
    assert result.stale is False

    row2 = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    assert row2.id == row1.id  # UPSERT 未换主键
    assert row2.competency_hash != hash1  # hash 已更新


@pytest.mark.asyncio
async def test_lifecycle_approve_triggers_retroactive(db_session, client):
    """简历先入库 → 岗位后发布能力模型 → T2 批量追溯打分, 排序正确."""
    # 3 份简历（不同年限+职级）
    r1 = _mk_resume(db_session, name="初级候选人", work_years=1, seniority="初级", skills="Python")
    r2 = _mk_resume(db_session, name="中级候选人", work_years=4, seniority="中级", skills="Python, Go")
    r3 = _mk_resume(db_session, name="资深候选人", work_years=8, seniority="高级", skills="Python, Go, K8s")

    # 岗位发布能力模型
    job = _mk_job(db_session, cm={
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 7},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    })

    # T2 触发批量打分
    with NO_LLM, HIGH_VEC:
        await on_competency_approved(db_session, job.id)

    rows = (
        db_session.query(MatchingResult)
        .filter_by(job_id=job.id)
        .order_by(MatchingResult.total_score.desc())
        .all()
    )
    assert len(rows) == 3

    # 初级候选人年限(1) < ymin(3)，分数最低
    assert rows[-1].resume_id == r1.id
    # 中级或资深在前（年限更合适/技能更多）
    assert rows[0].resume_id in (r2.id, r3.id)


@pytest.mark.asyncio
async def test_lifecycle_resume_rescored_after_parse_update(db_session):
    """简历第一次解析职级空 → 再次解析后 seniority 更新 → 重打分分数提升."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 0},
        "education": {},
        "job_level": "高级",
    })
    # 初次解析未推断职级 → seniority="" → match_ordinal 返回 2（中级默认）
    resume = _mk_resume(db_session, seniority="")

    with NO_LLM:
        await on_resume_parsed(db_session, resume.id)

    row1 = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    seniority_score1 = row1.seniority_score  # 中级 vs 高级 → 60

    # 模拟第二次 AI 解析推断为"高级"
    resume.seniority = "高级"
    db_session.commit()

    with NO_LLM:
        await MatchingService(db_session).score_pair(resume.id, job.id, triggered_by="T1")

    row2 = db_session.query(MatchingResult).filter_by(
        resume_id=resume.id, job_id=job.id
    ).one()
    assert row2.seniority_score > seniority_score1  # 职级对齐后分数提升


@pytest.mark.asyncio
async def test_lifecycle_multiple_resumes_competency_change(db_session):
    """多简历对同一岗位打分，能力模型变更后批量变 stale，单次重打分更新一行."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 2},
        "education": {},
        "job_level": "中级",
    })
    resumes = [_mk_resume(db_session, name=f"候选人{i}") for i in range(4)]

    with NO_LLM:
        for r in resumes:
            await MatchingService(db_session).score_pair(r.id, job.id, triggered_by="T1")

    rows_before = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert len(rows_before) == 4
    old_hash = rows_before[0].competency_hash

    # 变更能力模型
    job.competency_model = {
        "hard_skills": [],
        "experience": {"years_min": 5},
        "education": {},
        "job_level": "高级",
    }
    db_session.commit()
    db_session.expire_all()

    # 重打分一条
    target_resume = resumes[0]
    with NO_LLM:
        await MatchingService(db_session).score_pair(target_resume.id, job.id)

    rows_after = db_session.query(MatchingResult).filter_by(job_id=job.id).all()
    assert len(rows_after) == 4  # 行数不变

    updated = next(r for r in rows_after if r.resume_id == target_resume.id)
    assert updated.competency_hash != old_hash  # hash 已刷新

    # 其余 3 行 hash 未更新（依然是旧 hash → stale）
    for r in rows_after:
        if r.resume_id != target_resume.id:
            assert r.competency_hash == old_hash
