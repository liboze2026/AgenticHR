"""F2 真实业务场景测试."""
import pytest
from unittest.mock import patch, AsyncMock
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
LOW_VEC = patch(
    "app.modules.matching.scorers.skill._max_vector_similarity",
    return_value=0.1,
)


def _mk_resume(session, **kw):
    defaults = dict(
        name="候选人", phone="", skills="Python",
        work_experience="", work_years=3, education="本科",
        seniority="中级", ai_parsed="yes", source="manual",
    )
    defaults.update(kw)
    r = Resume(**defaults)
    session.add(r)
    session.commit()
    return r


def _mk_job(session, cm=None, **kw):
    defaults = dict(
        title="后端工程师", is_active=True, required_skills="",
        competency_model=cm or {
            "hard_skills": [],
            "experience": {"years_min": 3, "years_max": 5},
            "education": {"min_level": "本科"},
            "job_level": "中级",
        },
        competency_model_status="approved",
    )
    defaults.update(kw)
    j = Job(**defaults)
    session.add(j)
    session.commit()
    return j


@pytest.mark.asyncio
async def test_overqualified_candidate_experience_dips(db_session):
    """经验过剩：15 年经验，岗位要求 3-5 年 → experience_score 低于 100（扣分）, 但有 60 分下限."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 3, "years_max": 5},
        "education": {"min_level": "本科"},
        "job_level": "中级",
    })
    resume = _mk_resume(db_session, work_years=15, seniority="专家")

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    # 15 年超 ymax=5，扣分: 100 - (15-5)*10 = 0 → max(60, 0) = 60
    assert result.experience_score == 60.0
    # 整体分数仍然合理（60+ 专家 seniority=100, 无 gate）
    assert result.total_score > 30


@pytest.mark.asyncio
async def test_fresh_grad_low_experience(db_session):
    """应届生: 0 年经验, 本科, 初级, 技能有 Python → experience_score 为 0, hard gate 因 Python 命中而通过."""
    job = _mk_job(db_session, cm={
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 5},
        "education": {"min_level": "本科"},
        "job_level": "初级",
    })
    resume = _mk_resume(db_session, work_years=0, seniority="初级", skills="Python")

    with NO_LLM, HIGH_VEC:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    # 年限 0 < ymin=3 → experience_score = 0/3 * 100 = 0
    assert result.experience_score == 0.0
    # Python 命中（sim=0.95 >= threshold=0.75）→ hard gate pass
    assert result.hard_gate_passed is True
    # experience 拖低了总分（经验权重 30%），但技能/职级/学历分高 → 总分在 40-80 区间
    assert result.total_score < 80
    assert "经验不足" in result.tags


@pytest.mark.asyncio
async def test_career_changer_low_skill_industry(db_session):
    """转行候选人: 工作年限高但技能不匹配, 行业也不对 → skill_score + industry_score 低."""
    job = _mk_job(db_session, cm={
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 10, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    })
    resume = _mk_resume(
        db_session,
        work_years=8, seniority="高级",
        skills="Excel, 财务分析",  # 与 Python 无关
        work_experience="在制造业担任财务分析师 8 年",  # 非互联网
    )

    with NO_LLM, LOW_VEC:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    # Python 未命中 → hard gate fail
    assert result.hard_gate_passed is False
    assert "Python" in result.missing_must_haves
    assert result.total_score <= 29.0


@pytest.mark.asyncio
async def test_near_perfect_match(db_session):
    """高度匹配: 所有维度接近满分 → tag = 高匹配, total ≥ 80.

    注意: skill_score 由向量相似度决定, HIGH_VEC mock 返回 0.95 → skill=95.0.
    要得到 skill=100 需 canonical_id 精确匹配 (无 skills 表时不可用).
    因此 total_score 实际约 98 而非 100.
    """
    job = _mk_job(db_session, cm={
        "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
        "experience": {"years_min": 3, "years_max": 10, "industries": ["互联网"]},
        "education": {"min_level": "本科"},
        "job_level": "高级",
    })
    resume = _mk_resume(
        db_session,
        work_years=5, seniority="高级", education="本科",
        skills="Python",
        work_experience="在互联网公司工作 5 年",
    )

    with NO_LLM, HIGH_VEC:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.hard_gate_passed is True
    assert result.total_score >= 80.0
    assert "高匹配" in result.tags


@pytest.mark.asyncio
async def test_borderline_tag_threshold_59_9_is_low(db_session):
    """边界: total = 59.9 → tag 是 低匹配 (不是 中匹配); 60.0 → 中匹配."""
    from app.modules.matching.scorers.aggregator import derive_tags

    # 59.9 → 低匹配
    tags_low = derive_tags(
        total_score=59.9, hard_gate_passed=True, missing=[],
        education_score=100.0, experience_score=100.0,
    )
    assert "低匹配" in tags_low
    assert "中匹配" not in tags_low

    # 60.0 → 中匹配
    tags_mid = derive_tags(
        total_score=60.0, hard_gate_passed=True, missing=[],
        education_score=100.0, experience_score=100.0,
    )
    assert "中匹配" in tags_mid
    assert "低匹配" not in tags_mid


@pytest.mark.asyncio
async def test_borderline_high_match_threshold(db_session):
    """边界: total = 79.9 → 中匹配; 80.0 → 高匹配."""
    from app.modules.matching.scorers.aggregator import derive_tags

    tags_mid = derive_tags(
        total_score=79.9, hard_gate_passed=True, missing=[],
        education_score=100.0, experience_score=100.0,
    )
    assert "中匹配" in tags_mid

    tags_high = derive_tags(
        total_score=80.0, hard_gate_passed=True, missing=[],
        education_score=100.0, experience_score=100.0,
    )
    assert "高匹配" in tags_high


@pytest.mark.asyncio
async def test_education_below_requirement_tagged(db_session):
    """学历不达标 → education_score < 100. tag '学历不达标' 在 education_score < 50 时触发.

    derive_tags 阈值: education_score < 50 → '学历不达标'.
    本科 vs 硕士: score = 100 - (3-2)*40 = 60 (不触发标签).
    大专 vs 硕士: score = 100 - (3-1)*40 = 20 (< 50, 触发标签).
    """
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 0},
        "education": {"min_level": "硕士"},
        "job_level": "中级",
    })
    # 大专 vs 硕士 → education_score = 20 < 50 → 触发 '学历不达标'
    resume = _mk_resume(db_session, education="大专")

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.education_score < 50.0
    assert "学历不达标" in result.tags


@pytest.mark.asyncio
async def test_education_below_but_above_50_no_tag(db_session):
    """本科 vs 硕士: education_score=60 (≥50) → 不触发 '学历不达标' tag, 但分数低于满分."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 0},
        "education": {"min_level": "硕士"},
        "job_level": "中级",
    })
    resume = _mk_resume(db_session, education="本科")

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.education_score == 60.0  # 100 - (3-2)*40
    assert "学历不达标" not in result.tags


@pytest.mark.asyncio
async def test_experience_insufficient_tagged(db_session):
    """经验不足 → tag 包含 '经验不足'."""
    job = _mk_job(db_session, cm={
        "hard_skills": [],
        "experience": {"years_min": 5, "years_max": 10},
        "education": {},
        "job_level": "中级",
    })
    resume = _mk_resume(db_session, work_years=1)  # 1 年 < 5 年

    with NO_LLM:
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.experience_score < 50.0
    assert "经验不足" in result.tags
