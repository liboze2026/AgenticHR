"""F2 硬门槛边界条件测试."""
import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.matching.scorers.aggregator import aggregate, derive_tags
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
LOW_VEC = patch(
    "app.modules.matching.scorers.skill._max_vector_similarity",
    return_value=0.1,
)


def _mk_resume(session, **kw):
    defaults = dict(
        name="测试候选人", phone="", skills="Python",
        work_years=5, education="本科", seniority="高级",
        ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, cm, **kw):
    defaults = dict(
        title="测试岗", is_active=True, required_skills="",
        competency_model=cm,
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


@pytest.mark.asyncio
async def test_zero_hard_skills_no_gate(db_session):
    """zero hard_skills → missing_must_haves 一定为空, 无硬门槛."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 0},
        "education": {},
        "job_level": "中级",
    })
    resume = _mk_resume(db_session)

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.missing_must_haves == []
    assert result.hard_gate_passed is True
    assert result.total_score > 29.0  # 无 gate，不压缩


@pytest.mark.asyncio
async def test_three_missing_must_haves_all_recorded(db_session):
    """3 个 must_have 全部缺失 → missing 列出全部 3 个, tags 包含前 3 条."""
    job = _mk_job(db_session, cm={
        "hard_skills": [
            {"name": "Java", "weight": 5, "must_have": True, "canonical_id": None},
            {"name": "Kafka", "weight": 5, "must_have": True, "canonical_id": None},
            {"name": "AWS", "weight": 5, "must_have": True, "canonical_id": None},
        ],
        "experience": {"years_min": 0},
        "education": {},
        "job_level": "中级",
    })
    resume = _mk_resume(db_session, skills="Python")  # 无任何匹配

    with NO_LLM, LOW_VEC:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert len(result.missing_must_haves) == 3
    assert set(result.missing_must_haves) == {"Java", "Kafka", "AWS"}
    assert result.hard_gate_passed is False
    # tags 最多记录前 3 个缺失技能
    missing_tags = [t for t in result.tags if t.startswith("必须项缺失")]
    assert len(missing_tags) == 3


@pytest.mark.asyncio
async def test_all_must_have_matched_gate_passed(db_session):
    """所有 must_have 均命中 → hard_gate_passed=True."""
    job = _mk_job(db_session, cm={
        "hard_skills": [
            {"name": "Python", "weight": 10, "must_have": True, "canonical_id": None},
            {"name": "Go", "weight": 8, "must_have": True, "canonical_id": None},
        ],
        "experience": {"years_min": 0},
        "education": {},
        "job_level": "高级",
    })
    resume = _mk_resume(db_session, skills="Python, Go")

    with NO_LLM, HIGH_VEC:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.hard_gate_passed is True
    assert result.missing_must_haves == []
    assert result.total_score > 29.0


@pytest.mark.asyncio
async def test_mixed_must_optional_only_must_counts(db_session):
    """mixed: optional 缺失不触发硬门槛; 仅 must_have 缺失才计入 missing."""
    job = _mk_job(db_session, cm={
        "hard_skills": [
            {"name": "Python", "weight": 10, "must_have": True, "canonical_id": None},
            {"name": "Kubernetes", "weight": 5, "must_have": False, "canonical_id": None},
        ],
        "experience": {"years_min": 0},
        "education": {},
        "job_level": "中级",
    })
    # 只有 Python，K8s 可选缺失
    resume = _mk_resume(db_session, skills="Python")

    with NO_LLM, HIGH_VEC:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.hard_gate_passed is True
    assert result.missing_must_haves == []


def test_hard_gate_boundary_exactly_29(monkeypatch):
    """raw * 0.4 == 29.0 exactly → total == 29.0 (boundary 不超出)."""
    # raw = 72.5 → 72.5 * 0.4 = 29.0
    weights = {"skill_match": 100, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    dim_scores = {"skill": 72.5, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    result = aggregate(dim_scores, ["MissingSkill"], weights)
    assert result["total_score"] == 29.0
    assert result["hard_gate_passed"] is False


def test_hard_gate_boundary_30_caps_to_29():
    """raw * 0.4 = 30.0 → capped to 29.0."""
    weights = {"skill_match": 100, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    dim_scores = {"skill": 75.0, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    result = aggregate(dim_scores, ["MissingSkill"], weights)
    # 75 * 0.4 = 30.0 → min(30.0, 29.0) = 29.0
    assert result["total_score"] == 29.0


def test_hard_gate_very_low_score_preserved():
    """raw * 0.4 = 5.0 → 保留 5.0 (低于 cap)."""
    weights = {"skill_match": 100, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    dim_scores = {"skill": 12.5, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    result = aggregate(dim_scores, ["MissingSkill"], weights)
    assert result["total_score"] == 5.0


def test_hard_gate_zero_score_stays_zero():
    """全零分 + gate → total = 0."""
    weights = {"skill_match": 35, "experience": 30, "seniority": 15, "education": 10, "industry": 10}
    dim_scores = {"skill": 0, "experience": 0, "seniority": 0, "education": 0, "industry": 0}
    result = aggregate(dim_scores, ["SomeMissingSkill"], weights)
    assert result["total_score"] == 0.0
    assert result["hard_gate_passed"] is False


def test_tags_truncate_to_3_missing():
    """缺失 4 个技能, derive_tags 只列出前 3 条必须项缺失 tag."""
    tags = derive_tags(
        total_score=10.0,
        hard_gate_passed=False,
        missing=["A", "B", "C", "D"],
        education_score=100.0,
        experience_score=100.0,
    )
    missing_tags = [t for t in tags if t.startswith("必须项缺失")]
    assert len(missing_tags) == 3


@pytest.mark.asyncio
async def test_hard_gate_rescore_with_new_weights(db_session):
    """硬门槛触发后，更改 scoring_weights 文件 → 重打分时 new weights 生效 (weights_hash 改变)."""
    from app.core.settings.router import _CONFIG_PATH
    from app.modules.matching.models import MatchingResult
    import json

    job = _mk_job(db_session, cm={
        "hard_skills": [
            {"name": "COBOL", "weight": 10, "must_have": True, "canonical_id": None},
        ],
        "experience": {"years_min": 0},
        "education": {},
        "job_level": "中级",
    })
    resume = _mk_resume(db_session, skills="Python")

    with NO_LLM, LOW_VEC:
        await MatchingService(db_session).score_pair(resume.id, job.id)

    row1 = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
    assert row1.hard_gate_passed == 0
    hash_w1 = row1.weights_hash

    # 切换到不同权重（技能占比更高 → raw 变化, gate 压缩后结果也不同）
    new_weights = {"skill_match": 60, "experience": 20, "seniority": 10, "education": 5, "industry": 5}
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(new_weights), encoding="utf-8")

    try:
        with NO_LLM, LOW_VEC:
            await MatchingService(db_session).score_pair(resume.id, job.id)

        db_session.expire_all()
        row2 = db_session.query(MatchingResult).filter_by(resume_id=resume.id, job_id=job.id).one()
        # 由于 weights 变了，weights_hash 应不同
        assert row2.weights_hash != hash_w1
    finally:
        # 还原权重文件
        if _CONFIG_PATH.exists():
            _CONFIG_PATH.unlink()
