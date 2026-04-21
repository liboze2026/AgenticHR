"""F2 LLM 降级与异常处理测试."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.modules.matching.models import MatchingResult
from app.modules.matching.service import MatchingService
from app.modules.resume.models import Resume
from app.modules.screening.models import Job
from app.core.llm.provider import LLMError


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
            "hard_skills": [{"name": "Python", "weight": 10, "must_have": True, "canonical_id": None}],
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


HIGH_VEC = patch(
    "app.modules.matching.scorers.skill._max_vector_similarity",
    return_value=0.95,
)


@pytest.mark.asyncio
async def test_llm_error_falls_back_to_deterministic(db_session):
    """LLM 抛 LLMError → 打分成功, evidence 含确定性文本 '匹配到 Python'."""
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    with HIGH_VEC, patch(
        "app.modules.matching.scorers.evidence.enhance_evidence_with_llm",
        new=AsyncMock(side_effect=LLMError("mock LLM error")),
    ):
        # enhance_evidence_with_llm 内部已处理 LLMError, 不应在此层抛出
        # 但 service.py 调用的是 service 模块导入的 enhance_evidence_with_llm
        # 直接让 service 调用真实函数, 内部 _call_llm 报错
        with patch("app.modules.matching.scorers.evidence._call_llm",
                   new=AsyncMock(side_effect=LLMError("mock"))):
            result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.total_score > 0
    # evidence 里 skill 维度应有确定性文本
    skill_ev = result.evidence.get("skill", [])
    assert len(skill_ev) >= 1
    assert "Python" in skill_ev[0].text


@pytest.mark.asyncio
async def test_generic_exception_falls_back_gracefully(db_session):
    """LLM 抛 generic Exception → 打分成功, 不崩溃."""
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    with HIGH_VEC, patch(
        "app.modules.matching.scorers.evidence._call_llm",
        new=AsyncMock(side_effect=RuntimeError("network error")),
    ):
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert result.total_score > 0
    assert result.hard_gate_passed is True


@pytest.mark.asyncio
async def test_llm_returns_partial_dict_other_dims_deterministic(db_session):
    """LLM 只返回 skill 维度 → skill 用 LLM 文本, 其他维度保留 deterministic."""
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    llm_out = {"skill": ["这是 LLM 生成的技能证据"]}

    with HIGH_VEC, patch(
        "app.modules.matching.scorers.evidence._call_llm",
        new=AsyncMock(return_value=llm_out),
    ):
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    # skill 维度被 LLM 覆盖
    skill_ev = result.evidence.get("skill", [])
    if skill_ev:
        assert "LLM" in skill_ev[0].text or "技能" in skill_ev[0].text

    # experience 维度保留 deterministic（含工作年限信息）
    exp_ev = result.evidence.get("experience", [])
    assert len(exp_ev) >= 1
    assert "年" in exp_ev[0].text


@pytest.mark.asyncio
async def test_llm_disabled_via_setting_no_call(db_session, monkeypatch):
    """matching_evidence_llm_enabled=False → LLM 完全不调用, 证据为纯 deterministic."""
    from app.config import settings
    monkeypatch.setattr(settings, "matching_evidence_llm_enabled", False)

    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    call_count = 0

    async def mock_call_llm(prompt):
        nonlocal call_count
        call_count += 1
        return {}

    with HIGH_VEC, patch(
        "app.modules.matching.scorers.evidence._call_llm",
        new=AsyncMock(side_effect=mock_call_llm),
    ):
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    assert call_count == 0  # LLM 未被调用
    assert result.total_score > 0


@pytest.mark.asyncio
async def test_llm_returns_wrong_types_coerced_to_string(db_session):
    """LLM 返回 int/bool 代替 str 时, enhance_evidence_with_llm 应将其强转为 string.
    None 值应被跳过以保留 deterministic 文本.
    这修复了 F2 的一个真实 bug: 缺少类型校验导致 Pydantic ValidationError.
    """
    job = _mk_job(db_session)
    resume = _mk_resume(db_session)

    # 返回非 string 列表：skill 维度有 int + None，experience 维度有 bool
    llm_out = {"skill": [42, None], "experience": [True]}

    with HIGH_VEC, patch(
        "app.modules.matching.scorers.evidence._call_llm",
        new=AsyncMock(return_value=llm_out),
    ):
        result = await MatchingService(db_session).score_pair(resume.id, job.id)

    # 打分成功（不崩溃）
    assert result.total_score >= 0
    # int 被强转为 string "42"
    assert result.evidence["skill"][0].text == "42"
    # None 被跳过 — 保留 deterministic 文本（第二条证据保留）
    if len(result.evidence["skill"]) > 1:
        assert result.evidence["skill"][1].text.startswith("匹配到")
    # bool 被强转为 string "True"
    assert result.evidence["experience"][0].text == "True"
