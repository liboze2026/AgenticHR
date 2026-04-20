"""证据片段生成 — deterministic 定位 + 可选 LLM 文案增强."""
import re
from typing import Any


def _find_offset(pattern: str, text: str) -> tuple[int, int] | None:
    """忽略大小写找首次出现的 (start, end). 找不到返回 None."""
    if not pattern or not text:
        return None
    m = re.search(re.escape(pattern), text, re.IGNORECASE)
    if m:
        return [m.start(), m.end()]
    return None


_SKILL_SOURCES = ["skills", "project_experience", "work_experience", "self_evaluation"]


def _locate_skill(resume: Any, skill: str) -> dict:
    """在简历多个字段里找 skill 首次出现. 找不到返回 offset=None + source='' + 模板文本."""
    for src in _SKILL_SOURCES:
        text = getattr(resume, src, "") or ""
        off = _find_offset(skill, text)
        if off is not None:
            return {"text": f"匹配到 {skill}", "source": src, "offset": off}
    return {"text": f"匹配到 {skill}（简历原文未精确定位）", "source": "", "offset": None}


def build_deterministic_evidence(
    resume: Any,
    matched_skills: list[str],
    experience_range: tuple[int, int],
    matched_industries: list[str],
) -> dict:
    """返回按维度分组的 evidence dict."""
    evidence: dict = {"skill": [], "experience": [], "seniority": [], "education": [], "industry": []}

    for skill in matched_skills:
        evidence["skill"].append(_locate_skill(resume, skill))

    ymin, ymax = experience_range
    years = getattr(resume, "work_years", 0) or 0
    evidence["experience"].append({
        "text": f"工作年限 {years} 年，要求 {ymin}-{ymax} 年",
        "source": "work_years",
        "offset": None,
    })

    seniority = getattr(resume, "seniority", "") or ""
    if seniority:
        evidence["seniority"].append({
            "text": f"职级推断：{seniority}",
            "source": "seniority",
            "offset": None,
        })

    education = getattr(resume, "education", "") or ""
    if education:
        evidence["education"].append({
            "text": f"学历：{education}",
            "source": "education",
            "offset": None,
        })

    for industry in matched_industries:
        work_exp = getattr(resume, "work_experience", "") or ""
        off = _find_offset(industry, work_exp)
        if off is not None:
            evidence["industry"].append({
                "text": f"行业匹配：{industry}",
                "source": "work_experience",
                "offset": off,
            })
        else:
            evidence["industry"].append({
                "text": f"行业匹配：{industry}（未精确定位）",
                "source": "",
                "offset": None,
            })

    return evidence


import json
import logging
from app.config import settings
from app.core.llm.parsing import extract_json
from app.core.llm.provider import LLMError, LLMProvider

_logger = logging.getLogger(__name__)

_EVIDENCE_PROMPT = """你是招聘简历评估专家。给定一份简历摘要和 5 维度匹配分，每维度生成 1-3 条自然语言证据片段。
每条 ≤ 30 字。只输出 JSON，字段为 skill/experience/seniority/education/industry, 值为字符串数组。
简历：{resume_name}（技能：{skills}）
分数：{dim_scores}
现有 deterministic 证据：{base_evidence}"""


async def _call_llm(prompt: str) -> dict:
    """发起 LLM 调用, 返回解析后的 dict. 失败抛 LLMError."""
    provider = LLMProvider()
    content = await provider.complete(
        messages=[{"role": "user", "content": prompt}],
        prompt_version="f2_evidence_v1",
        f_stage="F2",
        entity_type="matching_result",
        temperature=0.3,
        response_format="json",
    )
    return extract_json(content)


async def enhance_evidence_with_llm(
    base_evidence: dict,
    resume: Any,
    dim_scores: dict,
) -> dict:
    """把 LLM 生成的 text 覆盖到 base_evidence 对应项, source/offset 保留.
    LLM 失败时直接返回 base_evidence 不抛.
    """
    if not getattr(settings, "matching_evidence_llm_enabled", True):
        return base_evidence

    try:
        prompt = _EVIDENCE_PROMPT.format(
            resume_name=getattr(resume, "name", ""),
            skills=getattr(resume, "skills", ""),
            dim_scores=json.dumps(dim_scores, ensure_ascii=False),
            base_evidence=json.dumps(
                {k: [e["text"] for e in v] for k, v in base_evidence.items()},
                ensure_ascii=False,
            ),
        )
        llm_out = await _call_llm(prompt)
    except LLMError as e:
        _logger.info(f"LLM evidence failed, using deterministic only: {e}")
        return base_evidence
    except Exception as e:
        _logger.warning(f"LLM evidence unexpected error: {e}")
        return base_evidence

    # 覆盖 text, 保留 source/offset
    for dim, texts in (llm_out or {}).items():
        if dim not in base_evidence:
            continue
        for i, text in enumerate(texts or []):
            if i < len(base_evidence[dim]):
                base_evidence[dim][i]["text"] = text

    return base_evidence
