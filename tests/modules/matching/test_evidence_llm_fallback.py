import pytest
from unittest.mock import patch, AsyncMock
from app.modules.matching.scorers.evidence import enhance_evidence_with_llm
from app.core.llm.provider import LLMError


class _FakeResume:
    name = "张三"
    skills = "Python, Go"


@pytest.mark.asyncio
async def test_llm_success_overwrites_text():
    base_evidence = {
        "skill": [{"text": "匹配到 Python", "source": "skills", "offset": [0, 6]}],
        "experience": [{"text": "工作年限 5 年", "source": "work_years", "offset": None}],
        "seniority": [], "education": [], "industry": [],
    }
    llm_output = {
        "skill": ["Python 技能满分匹配"],
        "experience": ["5 年经验贴合要求"],
        "seniority": [], "education": [], "industry": [],
    }
    with patch("app.modules.matching.scorers.evidence._call_llm",
               new=AsyncMock(return_value=llm_output)):
        result = await enhance_evidence_with_llm(base_evidence, _FakeResume(), dim_scores={})

    # text 被覆盖, source/offset 保留
    assert result["skill"][0]["text"] == "Python 技能满分匹配"
    assert result["skill"][0]["source"] == "skills"
    assert result["skill"][0]["offset"] == [0, 6]
    assert result["experience"][0]["text"] == "5 年经验贴合要求"


@pytest.mark.asyncio
async def test_llm_failure_preserves_deterministic():
    base_evidence = {
        "skill": [{"text": "匹配到 Python", "source": "skills", "offset": [0, 6]}],
        "experience": [], "seniority": [], "education": [], "industry": [],
    }
    with patch("app.modules.matching.scorers.evidence._call_llm",
               new=AsyncMock(side_effect=LLMError("API down"))):
        result = await enhance_evidence_with_llm(base_evidence, _FakeResume(), dim_scores={})

    assert result["skill"][0]["text"] == "匹配到 Python"
    assert result["skill"][0]["offset"] == [0, 6]


@pytest.mark.asyncio
async def test_llm_shorter_output_extras_preserved():
    # LLM 只返回 1 条但 base 有 2 条 → 第一条覆盖, 第二条保留
    base_evidence = {
        "skill": [
            {"text": "匹配到 Python", "source": "skills", "offset": [0, 6]},
            {"text": "匹配到 Go", "source": "skills", "offset": [8, 10]},
        ],
        "experience": [], "seniority": [], "education": [], "industry": [],
    }
    with patch("app.modules.matching.scorers.evidence._call_llm",
               new=AsyncMock(return_value={"skill": ["Python 强匹配"]})):
        result = await enhance_evidence_with_llm(base_evidence, _FakeResume(), dim_scores={})

    assert result["skill"][0]["text"] == "Python 强匹配"
    assert result["skill"][1]["text"] == "匹配到 Go"
